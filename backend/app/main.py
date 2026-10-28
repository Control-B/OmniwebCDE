import json
import logging
import uuid
from contextlib import asynccontextmanager

import jwt
from fastapi import FastAPI, Response, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import select

from .api import router
from .builder import pipeline, preview
from .builder_api import router as builder_router
from .config import get_settings
from .database import SessionLocal, engine
from .models import Base, Membership, Organization, User, Workspace, WorkspaceState
from .projects_api import router as projects_router
from .security import DEV_ORG_ID, DEV_USER_ID, signing_secret

settings = get_settings()
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger("omniweb")
REQUESTS = Counter(
    "omniweb_http_requests_total",
    "HTTP requests processed",
    ["method", "route", "status"],
)
LATENCY = Histogram(
    "omniweb_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "route"],
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.environment == "development":
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            if not await db.get(Organization, DEV_ORG_ID):
                db.add(Organization(id=DEV_ORG_ID, name="Omniweb Labs", slug="omniweb-labs"))
                db.add(
                    User(
                        id=DEV_USER_ID,
                        oidc_subject="local-development-user",
                        email="dev@omniweb.local",
                        display_name="Avery Morgan",
                    )
                )
                db.add(
                    Membership(
                        organization_id=DEV_ORG_ID,
                        user_id=DEV_USER_ID,
                        role="owner",
                    )
                )
                await db.commit()
    await pipeline.resume_all(settings)
    yield
    await preview.stop_all()
    await engine.dispose()


app = FastAPI(
    title="Omniweb API",
    version="0.1.0",
    description="Multi-tenant control plane: identity, projects, and cloud workspaces",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_frontend_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
app.include_router(router)
app.include_router(projects_router)
app.include_router(builder_router)


@app.middleware("http")
async def security_headers(request, call_next):
    route = request.url.path
    with LATENCY.labels(request.method, route).time():
        response = await call_next(request)
    REQUESTS.labels(request.method, route, response.status_code).inc()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/healthz", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["operations"])
async def readiness() -> dict[str, str]:
    async with SessionLocal() as db:
        await db.execute(select(1))
    return {"status": "ready"}


@app.get("/metrics", tags=["operations"], include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.websocket("/api/v1/terminal/{workspace_id}")
async def terminal(websocket: WebSocket, workspace_id: uuid.UUID) -> None:
    origin = websocket.headers.get("origin")
    if origin not in settings.allowed_frontend_origins:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Origin rejected")
        return
    token = websocket.query_params.get("access_token", "")
    secret = signing_secret(settings)
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        if claims.get("workspace") != str(workspace_id) or claims.get("kind") != "console":
            raise jwt.InvalidTokenError("Token scope mismatch")
    except jwt.PyJWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session")
        return
    async with SessionLocal() as db:
        workspace = await db.scalar(
            select(Workspace).where(
                Workspace.id == workspace_id,
                Workspace.organization_id == uuid.UUID(claims["org"]),
                Workspace.state == WorkspaceState.READY,
            )
        )
    if not workspace:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Workspace unavailable")
        return
    await websocket.accept()
    await websocket.send_text(
        json.dumps(
            {
                "type": "output",
                "data": "\u001b[32mConnected to Omniweb workspace\u001b[0m\r\n"
                "developer@workspace:~/project$ ",
            }
        )
    )
    try:
        while True:
            message = json.loads(await websocket.receive_text())
            if message.get("type") == "resize":
                continue
            if message.get("type") == "input":
                data = str(message.get("data", ""))
                # Development mock only. Production terminates TLS at the access service and
                # bridges the authorized stream to Coder's workspace-agent terminal API.
                await websocket.send_text(json.dumps({"type": "output", "data": data}))
                if data in {"\r", "\n"}:
                    await websocket.send_text(
                        json.dumps({"type": "output", "data": "developer@workspace:~/project$ "})
                    )
    except WebSocketDisconnect:
        logger.info("terminal disconnected workspace=%s", workspace_id)
