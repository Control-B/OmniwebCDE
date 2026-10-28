import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import get_db
from .models import CloudConnection, Workspace, WorkspaceState
from .providers.digitalocean import DigitalOceanAdapter
from .schemas import (
    AccessLink,
    CloudConnectionCreate,
    CloudConnectionView,
    DashboardSummary,
    Principal,
    Region,
    Size,
    WorkspaceCreate,
    WorkspaceEventView,
    WorkspaceView,
)
from .security import encrypt_secret, get_principal
from .services.workspaces import create_workspace, summary, tenant_workspace, transition

router = APIRouter(prefix="/api/v1")


@router.get("/me", response_model=Principal)
async def me(principal: Principal = Depends(get_principal)) -> Principal:
    return principal


@router.get("/dashboard", response_model=DashboardSummary)
async def dashboard(
    db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
) -> DashboardSummary:
    return await summary(db, principal)


@router.get("/cloud-connections", response_model=list[CloudConnectionView])
async def list_connections(
    db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
) -> list[CloudConnection]:
    return list(
        (
            await db.scalars(
                select(CloudConnection)
                .where(CloudConnection.organization_id == principal.organization_id)
                .order_by(CloudConnection.created_at.desc())
            )
        ).all()
    )


@router.post(
    "/cloud-connections",
    response_model=CloudConnectionView,
    status_code=status.HTTP_201_CREATED,
)
async def connect_cloud(
    data: CloudConnectionCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> CloudConnection:
    token = data.token.get_secret_value()
    if len(token) < 8:
        raise HTTPException(status_code=422, detail="Token is too short")
    async with DigitalOceanAdapter(token, settings) as provider:
        account_id = await provider.validate()
    connection = CloudConnection(
        organization_id=principal.organization_id,
        provider="digitalocean",
        label=data.label,
        encrypted_token=encrypt_secret(token, settings),
        token_fingerprint=hashlib.sha256(token.encode()).hexdigest()[:10],
        provider_account_id=account_id,
        healthy=True,
        last_checked_at=datetime.now(UTC),
    )
    db.add(connection)
    await db.commit()
    await db.refresh(connection)
    return connection


@router.delete("/cloud-connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_cloud(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> Response:
    connection = await db.scalar(
        select(CloudConnection).where(
            CloudConnection.id == connection_id,
            CloudConnection.organization_id == principal.organization_id,
        )
    )
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    active = await db.scalar(
        select(Workspace.id).where(
            Workspace.cloud_connection_id == connection.id,
            Workspace.state.not_in([WorkspaceState.DELETED, WorkspaceState.FAILED]),
        )
    )
    if active:
        raise HTTPException(status_code=409, detail="Delete dependent workspaces first")
    await db.delete(connection)
    await db.commit()
    return Response(status_code=204)


@router.get("/catalog/regions", response_model=list[Region])
async def regions(
    settings: Settings = Depends(get_settings),
    _: Principal = Depends(get_principal),
) -> list[Region]:
    async with DigitalOceanAdapter("catalog", settings) as provider:
        return await provider.regions()


@router.get("/catalog/sizes", response_model=list[Size])
async def sizes(
    region: str | None = None,
    settings: Settings = Depends(get_settings),
    _: Principal = Depends(get_principal),
) -> list[Size]:
    async with DigitalOceanAdapter("catalog", settings) as provider:
        return await provider.sizes(region)


@router.get("/workspaces", response_model=list[WorkspaceView])
async def list_workspaces(
    db: AsyncSession = Depends(get_db), principal: Principal = Depends(get_principal)
) -> list[Workspace]:
    return list(
        (
            await db.scalars(
                select(Workspace)
                .where(
                    Workspace.organization_id == principal.organization_id,
                    Workspace.state != WorkspaceState.DELETED,
                )
                .order_by(Workspace.created_at.desc())
            )
        ).all()
    )


@router.post("/workspaces", response_model=WorkspaceView)
async def create(
    data: WorkspaceCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> Workspace:
    workspace, created = await create_workspace(db, data, principal, settings)
    response.status_code = 201 if created else 200
    return workspace


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceView)
async def get_workspace(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> Workspace:
    return await tenant_workspace(db, workspace_id, principal)


@router.get("/workspaces/{workspace_id}/events", response_model=list[WorkspaceEventView])
async def workspace_events(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list:
    workspace = await tenant_workspace(db, workspace_id, principal)
    return sorted(workspace.events, key=lambda event: event.created_at, reverse=True)


@router.post("/workspaces/{workspace_id}/{action}", response_model=WorkspaceView)
async def lifecycle(
    workspace_id: uuid.UUID,
    action: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> Workspace:
    workspace = await tenant_workspace(db, workspace_id, principal)
    if action == "stop":
        await transition(db, workspace, WorkspaceState.STOPPING, "Stop requested", principal.user_id)
        await transition(db, workspace, WorkspaceState.STOPPED, "Workspace stopped")
    elif action == "start":
        await transition(db, workspace, WorkspaceState.STARTING, "Start requested", principal.user_id)
        await transition(db, workspace, WorkspaceState.CONNECTING, "Waiting for workspace agent")
        await transition(db, workspace, WorkspaceState.READY, "Workspace agent connected")
    elif action == "restart":
        await transition(db, workspace, WorkspaceState.STOPPING, "Restart requested", principal.user_id)
        await transition(db, workspace, WorkspaceState.STOPPED, "Workspace stopped")
        await transition(db, workspace, WorkspaceState.STARTING, "Restarting workspace")
        await transition(db, workspace, WorkspaceState.CONNECTING, "Waiting for workspace agent")
        await transition(db, workspace, WorkspaceState.READY, "Workspace agent connected")
    elif action == "delete":
        await transition(db, workspace, WorkspaceState.DELETING, "Deletion approved", principal.user_id)
        connection = await db.get(CloudConnection, workspace.cloud_connection_id)
        if connection and workspace.external_resource_id:
            from .security import decrypt_secret

            token = decrypt_secret(connection.encrypted_token, settings)
            async with DigitalOceanAdapter(token, settings) as provider:
                await provider.delete_droplet(workspace.external_resource_id)
        await transition(db, workspace, WorkspaceState.DELETED, "Provider resource removed")
    else:
        raise HTTPException(status_code=404, detail="Unknown lifecycle action")
    await db.commit()
    await db.refresh(workspace)
    return workspace


def _access_token(workspace: Workspace, principal: Principal, settings: Settings, kind: str) -> str:
    secret = settings.encryption_key or "local-access-token-secret-change-me"
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(principal.user_id),
            "org": str(principal.organization_id),
            "workspace": str(workspace.id),
            "kind": kind,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            "nonce": str(uuid.uuid4()),
        },
        secret,
        algorithm="HS256",
    )


@router.post("/workspaces/{workspace_id}/access/{kind}", response_model=AccessLink)
async def access(
    workspace_id: uuid.UUID,
    kind: str,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> AccessLink:
    if kind not in {"ide", "console"}:
        raise HTTPException(status_code=404, detail="Unknown access mode")
    workspace = await tenant_workspace(db, workspace_id, principal)
    if workspace.state != WorkspaceState.READY:
        raise HTTPException(status_code=409, detail="Workspace is not ready")
    token = _access_token(workspace, principal, settings, kind)
    # This token is short-lived and scoped to one workspace and access mode.
    return AccessLink(url=f"/{kind}/{workspace.id}?access_token={token}", expires_in_seconds=300, kind=kind)
