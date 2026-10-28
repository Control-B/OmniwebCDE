import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import routing_policy, telemetry
from .config import Settings, get_settings
from .contracts import SERVER_ONLY_FIELDS, TaskRequest
from .database import SessionLocal, engine, get_db
from .execution_planner import NoStats, PlanContext, plan
from .inference_gateway import GatewayError, HttpGateway
from .model_registry import Registry
from .models import Base, ModelPolicy, RoutingPolicy
from .security import Caller, RateLimiter, audit, caller, platform_admin, redact, tenant_admin
from .task_classifier import classify

logger = logging.getLogger("omniweb.aaee")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if not settings.is_production:
        # Production schemas are managed with `alembic upgrade head`.
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await routing_policy.ensure_default(db)
        await db.commit()
    yield
    await engine.dispose()


app = FastAPI(title="Omniweb Adaptive AI Execution Engine", version="0.1.0", lifespan=lifespan)
app.state.gateway = HttpGateway(get_settings())
app.state.registry = Registry(app.state.gateway, get_settings().registry_cache_seconds)
app.state.rate_limiter = RateLimiter(get_settings())
telemetry.setup(app)


def registry(request: Request) -> Registry:
    return request.app.state.registry


def parse_task_request(raw: dict) -> TaskRequest:
    forbidden = sorted(SERVER_ONLY_FIELDS & set(raw))
    if forbidden:
        raise HTTPException(status_code=422, detail=f"These fields are set by server policy and cannot be supplied: {', '.join(forbidden)}")
    try:
        return TaskRequest.model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=redact(str(exc))[:2000]) from None


async def gateway_available(request: Request, identity: Caller, project_id: uuid.UUID | None) -> float:
    try:
        budgets = await request.app.state.gateway.budgets(identity, project_id)
    except GatewayError:
        return 0.0
    hard = [b["remaining_usd"] for b in budgets if b.get("hard_limit", True)]
    return min(hard) if hard else float("inf")


@app.get("/healthz")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/plan")
async def dry_run_plan(
    request: Request,
    raw: dict = Body(...),
    identity: Caller = Depends(caller),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Classify and plan a task without executing it or reserving budget."""
    body = parse_task_request(raw)
    active = await routing_policy.ensure_default(db)
    policy = routing_policy.effective(active.config)
    spec = classify(body, identity, policy, uuid.uuid4(), settings.default_task_budget_usd)
    try:
        models = await registry(request).load(db, identity)
    except GatewayError as exc:
        raise HTTPException(status_code=503, detail=f"Model registry unavailable: {exc}") from None
    available = min(spec.maximum_budget_usd, await gateway_available(request, identity, spec.project_id))
    ctx = PlanContext(budget_available_usd=available, execution_ceiling_usd=settings.default_execution_ceiling_usd,
                      production=settings.is_production)
    artifacts = {a.path: a.content or "" for a in body.input_artifacts}
    result = plan(spec, models, policy, NoStats(), ctx, artifacts)
    await db.commit()
    return {"spec": spec.model_dump(mode="json"), "plan": result, "policy_version": active.version}


class ModelPolicyInput(BaseModel):
    scope: Literal["platform", "tenant"] = "platform"
    enabled: bool = True
    priority: int = Field(default=0, ge=-100, le=100)
    family: Literal["gpt_oss", "hosted", "development"] | None = None
    hosting_mode: Literal["first_party_api", "inference_provider", "self_hosted"] | None = None
    validated_input_usd_per_mtok: float | None = Field(default=None, ge=0, le=1_000)
    validated_output_usd_per_mtok: float | None = Field(default=None, ge=0, le=1_000)
    validated_cached_usd_per_mtok: float | None = Field(default=None, ge=0, le=1_000)
    infra_usd_per_mtok: float | None = Field(default=None, ge=0, le=1_000)
    rate_limit_rpm: int | None = Field(default=None, ge=1, le=100_000)
    capabilities_add: list[Literal["structured_output", "tools", "vision", "reasoning", "prompt_caching"]] = Field(default_factory=list)
    capabilities_remove: list[str] = Field(default_factory=list, max_length=10)
    notes: str = Field(default="", max_length=500)


@app.get("/v1/admin/models")
async def admin_models(request: Request, identity: Caller = Depends(tenant_admin), db: AsyncSession = Depends(get_db)) -> list[dict]:
    try:
        models = await registry(request).load(db, identity)
    except GatewayError as exc:
        raise HTTPException(status_code=503, detail=f"Model registry unavailable: {exc}") from None
    return [m.view() for m in sorted(models, key=lambda m: (m.family, m.provider, m.model_id))]


@app.put("/v1/admin/models/{provider}/{model_id:path}")
async def put_model_policy(
    provider: str, model_id: str, body: ModelPolicyInput, request: Request,
    identity: Caller = Depends(tenant_admin), db: AsyncSession = Depends(get_db),
) -> dict:
    models = {m.key: m for m in await registry(request).load(db, identity)}
    model = models.get(f"{provider}/{model_id}")
    if not model:
        raise HTTPException(status_code=404, detail="Model is not in the gateway registry for this organization")
    if body.scope == "platform" and not identity.platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator access required for platform-wide model policy")
    if body.scope == "tenant" and model.billing_model != "customer" and any(
        v is not None for v in (body.validated_input_usd_per_mtok, body.validated_output_usd_per_mtok, body.infra_usd_per_mtok)
    ):
        raise HTTPException(status_code=403, detail="Organizations can only validate pricing for models on their own provider keys")
    if (body.validated_input_usd_per_mtok is None) != (body.validated_output_usd_per_mtok is None):
        raise HTTPException(status_code=422, detail="Validated pricing needs both input and output prices")
    scope = "platform" if body.scope == "platform" else str(identity.tenant_id)
    overlay = await db.scalar(select(ModelPolicy).where(ModelPolicy.scope == scope, ModelPolicy.provider == provider,
                                                        ModelPolicy.model_id == model_id))
    overlay = overlay or ModelPolicy(scope=scope, provider=provider, model_id=model_id)
    for field, value in body.model_dump(exclude={"scope"}).items():
        setattr(overlay, field, value)
    if body.validated_input_usd_per_mtok is not None or body.infra_usd_per_mtok is not None:
        overlay.validated_by = identity.user_id
        overlay.validated_at = datetime.now(UTC)
    db.add(overlay)
    await audit(db, identity, "model_policy.update", f"{provider}/{model_id}", body.model_dump())
    await db.commit()
    registry(request).invalidate()
    updated = {m.key: m for m in await registry(request).load(db, identity)}
    return updated[f"{provider}/{model_id}"].view()


class PolicyInput(BaseModel):
    config: dict = Field(default_factory=dict)
    notes: str = Field(default="", max_length=500)


class PolicyStatus(BaseModel):
    status: Literal["active", "shadow", "experiment", "retired", "draft"]
    traffic_percent: float = Field(default=0, ge=0, le=50)


def policy_view(policy: RoutingPolicy) -> dict:
    return {"version": policy.version, "status": policy.status, "traffic_percent": policy.traffic_percent, "notes": policy.notes,
            "config": policy.config, "created_at": policy.created_at.isoformat()}


@app.get("/v1/admin/policies")
async def list_policies(_: Caller = Depends(tenant_admin), db: AsyncSession = Depends(get_db)) -> list[dict]:
    return [policy_view(p) for p in await db.scalars(select(RoutingPolicy).order_by(RoutingPolicy.version.desc()))]


@app.post("/v1/admin/policies", status_code=201)
async def create_policy(body: PolicyInput, identity: Caller = Depends(platform_admin), db: AsyncSession = Depends(get_db)) -> dict:
    try:
        config = routing_policy.validate_config(body.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    latest = await db.scalar(select(RoutingPolicy).order_by(RoutingPolicy.version.desc()).limit(1))
    policy = RoutingPolicy(version=(latest.version if latest else 0) + 1, status="draft", config=config, notes=body.notes,
                           created_by=identity.user_id)
    db.add(policy)
    await audit(db, identity, "routing_policy.create", f"v{policy.version}", {"notes": body.notes})
    await db.commit()
    return policy_view(policy)


@app.post("/v1/admin/policies/{version}/status")
async def set_policy_status(version: int, body: PolicyStatus, identity: Caller = Depends(platform_admin),
                            db: AsyncSession = Depends(get_db)) -> dict:
    policy = await db.scalar(select(RoutingPolicy).where(RoutingPolicy.version == version))
    if not policy:
        raise HTTPException(status_code=404, detail="Unknown policy version")
    if body.status == "active":
        for other in await db.scalars(select(RoutingPolicy).where(RoutingPolicy.status == "active", RoutingPolicy.version != version)):
            other.status = "retired"
        policy.traffic_percent = 100
    elif policy.status == "active":
        raise HTTPException(status_code=409, detail="Activate another version before changing the active policy")
    else:
        policy.traffic_percent = body.traffic_percent if body.status == "experiment" else 0
    policy.status = body.status
    await audit(db, identity, "routing_policy.status", f"v{version}", body.model_dump())
    await db.commit()
    return policy_view(policy)
