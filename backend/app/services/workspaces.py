import uuid
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import Settings
from ..models import CloudConnection, Workspace, WorkspaceEvent, WorkspaceState
from ..providers.digitalocean import DigitalOceanAdapter
from ..schemas import DashboardSummary, Principal, WorkspaceCreate
from ..security import decrypt_secret

TRANSITIONS: dict[WorkspaceState, set[WorkspaceState]] = {
    WorkspaceState.REQUESTED: {WorkspaceState.VALIDATING, WorkspaceState.DELETING},
    WorkspaceState.VALIDATING: {WorkspaceState.PROVISIONING, WorkspaceState.FAILED},
    WorkspaceState.PROVISIONING: {WorkspaceState.BOOTSTRAPPING, WorkspaceState.FAILED},
    WorkspaceState.BOOTSTRAPPING: {WorkspaceState.CONNECTING, WorkspaceState.FAILED},
    WorkspaceState.CONNECTING: {WorkspaceState.READY, WorkspaceState.FAILED},
    WorkspaceState.READY: {
        WorkspaceState.STOPPING,
        WorkspaceState.REBUILDING,
        WorkspaceState.DELETING,
        WorkspaceState.RECOVERING,
    },
    WorkspaceState.STOPPING: {WorkspaceState.STOPPED, WorkspaceState.FAILED},
    WorkspaceState.STOPPED: {
        WorkspaceState.STARTING,
        WorkspaceState.REBUILDING,
        WorkspaceState.DELETING,
    },
    WorkspaceState.STARTING: {WorkspaceState.CONNECTING, WorkspaceState.FAILED},
    WorkspaceState.REBUILDING: {WorkspaceState.PROVISIONING, WorkspaceState.FAILED},
    WorkspaceState.DELETING: {WorkspaceState.DELETED, WorkspaceState.FAILED},
    WorkspaceState.FAILED: {
        WorkspaceState.RECOVERING,
        WorkspaceState.DELETING,
    },
    WorkspaceState.RECOVERING: {
        WorkspaceState.VALIDATING,
        WorkspaceState.READY,
        WorkspaceState.FAILED,
    },
    WorkspaceState.DELETED: set(),
}


async def transition(
    db: AsyncSession,
    workspace: Workspace,
    target: WorkspaceState,
    reason: str,
    actor_id: uuid.UUID | None = None,
) -> None:
    if target not in TRANSITIONS[workspace.state]:
        raise ValueError(f"Invalid workspace transition: {workspace.state} -> {target}")
    previous = workspace.state
    workspace.state = target
    db.add(
        WorkspaceEvent(
            workspace_id=workspace.id,
            organization_id=workspace.organization_id,
            from_state=previous,
            to_state=target,
            reason=reason,
            actor_id=actor_id,
        )
    )
    await db.flush()


async def tenant_workspace(
    db: AsyncSession, workspace_id: uuid.UUID, principal: Principal
) -> Workspace:
    workspace = await db.scalar(
        select(Workspace)
        .where(
            Workspace.id == workspace_id,
            Workspace.organization_id == principal.organization_id,
            Workspace.state != WorkspaceState.DELETED,
        )
        .options(selectinload(Workspace.events))
    )
    if not workspace:
        # Deliberately hide whether a cross-tenant resource exists.
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def create_workspace(
    db: AsyncSession, data: WorkspaceCreate, principal: Principal, settings: Settings
) -> tuple[Workspace, bool]:
    existing = await db.scalar(
        select(Workspace).where(
            Workspace.organization_id == principal.organization_id,
            Workspace.idempotency_key == data.idempotency_key,
        )
    )
    if existing:
        return existing, False

    connection = await db.scalar(
        select(CloudConnection).where(
            CloudConnection.id == data.cloud_connection_id,
            CloudConnection.organization_id == principal.organization_id,
            CloudConnection.healthy.is_(True),
        )
    )
    if not connection:
        raise HTTPException(status_code=422, detail="Healthy cloud connection required")

    token = decrypt_secret(connection.encrypted_token, settings)
    async with DigitalOceanAdapter(token, settings) as provider:
        sizes = await provider.sizes(data.region)
        selected = next((item for item in sizes if item.slug == data.size and item.available), None)
        if not selected:
            raise HTTPException(status_code=422, detail="Selected size is unavailable in this region")
        if abs(selected.monthly_usd - data.approved_estimated_monthly_usd) > Decimal("0.01"):
            raise HTTPException(status_code=409, detail="Price changed; review and approve the new estimate")

        workspace = Workspace(
            organization_id=principal.organization_id,
            owner_id=principal.user_id,
            cloud_connection_id=connection.id,
            name=data.name,
            region=data.region,
            size=data.size,
            image=data.image,
            template=data.template,
            idempotency_key=data.idempotency_key,
            estimated_monthly_usd=selected.monthly_usd,
        )
        db.add(workspace)
        await db.flush()
        db.add(
            WorkspaceEvent(
                workspace_id=workspace.id,
                organization_id=workspace.organization_id,
                to_state=WorkspaceState.REQUESTED,
                reason="Creation approved by user",
                actor_id=principal.user_id,
            )
        )
        await transition(db, workspace, WorkspaceState.VALIDATING, "Request validated")
        await transition(db, workspace, WorkspaceState.PROVISIONING, "Provisioning started")

        # Production uses a Temporal activity to mint a short-lived Coder agent token.
        # No provider or Omniweb credential is included in cloud-init.
        cloud_init = "#cloud-config\nusers:\n  - name: developer\n    shell: /bin/bash\n"
        workspace.external_resource_id = await provider.create_droplet(
            name=f"omniweb-{workspace.id.hex[:10]}",
            region=data.region,
            size=data.size,
            image=data.image,
            user_data=cloud_init,
            tags=["omniweb", f"org-{principal.organization_id}"],
        )
        await transition(db, workspace, WorkspaceState.BOOTSTRAPPING, "Droplet created")
        await transition(db, workspace, WorkspaceState.CONNECTING, "Agent registration pending")
        if settings.mock_infrastructure:
            workspace.coder_workspace_id = f"mock-coder-{workspace.id}"
            await transition(db, workspace, WorkspaceState.READY, "Mock workspace agent connected")
        await db.commit()
        await db.refresh(workspace)
        return workspace, True


async def summary(db: AsyncSession, principal: Principal) -> DashboardSummary:
    rows = (
        await db.execute(
            select(Workspace.state, func.count(Workspace.id), func.sum(Workspace.estimated_monthly_usd))
            .where(
                Workspace.organization_id == principal.organization_id,
                Workspace.state != WorkspaceState.DELETED,
            )
            .group_by(Workspace.state)
        )
    ).all()
    counts = {state: count for state, count, _ in rows}
    total_cost = sum((Decimal(str(cost or 0)) for _, _, cost in rows), Decimal("0"))
    connection_count = await db.scalar(
        select(func.count(CloudConnection.id)).where(
            CloudConnection.organization_id == principal.organization_id
        )
    )
    return DashboardSummary(
        total=sum(counts.values()),
        running=counts.get(WorkspaceState.READY, 0),
        stopped=counts.get(WorkspaceState.STOPPED, 0),
        failed=counts.get(WorkspaceState.FAILED, 0),
        cloud_connections=connection_count or 0,
        estimated_monthly_usd=total_cost,
    )
