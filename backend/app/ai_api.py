"""Adaptive AI Execution Engine routes: task status, approvals, CDE agent tasks, and admin views.

The browser never talks to AAEE. These routes authenticate the user, check project and
workspace access here, and forward a short-lived service token whose claims come from the
principal. AAEE enforces tenant isolation and administrator gates again on its side.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .database import get_db
from .models import WorkspaceAgentTask
from .projects_api import audit, project_access
from .schemas import Principal
from .security import get_principal, require_admin
from .services import aaee
from .services.workspaces import tenant_workspace

router = APIRouter(prefix="/api/v1")
ADMIN_ROLES = {"owner", "admin"}


@router.get("/ai/engine")
async def engine_access(
    principal: Principal = Depends(get_principal), settings: Settings = Depends(get_settings)
) -> dict:
    available = False
    if settings.aaee_enabled:
        try:
            async with aaee.http_client(settings, 3) as client:
                available = (await client.get("/healthz")).status_code == 200
        except Exception:  # noqa: BLE001  any failure means unavailable
            available = False
    return {
        "available": available,
        "tenant_admin": principal.role in ADMIN_ROLES,
        "platform_admin": aaee.is_platform_admin(settings, principal),
    }


async def _visible(db: AsyncSession, principal: Principal, task: dict) -> dict:
    """Members see tasks for projects they can access; administrators see the organization's."""
    if principal.role in ADMIN_ROLES:
        return task
    if task.get("project_id"):
        await project_access(db, uuid.UUID(task["project_id"]), principal)
        return task
    if task.get("workspace_id"):
        await tenant_workspace(db, uuid.UUID(task["workspace_id"]), principal)
        return task
    raise HTTPException(status_code=404, detail="Task not found")


@router.get("/ai/tasks")
async def list_tasks(
    project_id: uuid.UUID | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> list[dict]:
    if project_id:
        await project_access(db, project_id, principal)
    elif principal.role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403, detail="Choose a project, or ask an organization admin"
        )
    params: dict[str, Any] = {"limit": limit}
    if project_id:
        params["project_id"] = str(project_id)
    if status_filter:
        params["status"] = status_filter
    return await aaee.proxy(
        settings, principal, "GET", "/v1/tasks", params=params, project_id=project_id
    )


@router.get("/ai/tasks/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    return await _visible(
        db, principal, await aaee.proxy(settings, principal, "GET", f"/v1/tasks/{task_id}")
    )


@router.post("/ai/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    await _visible(
        db, principal, await aaee.proxy(settings, principal, "GET", f"/v1/tasks/{task_id}")
    )
    return await aaee.proxy(settings, principal, "POST", f"/v1/tasks/{task_id}/cancel")


class DecisionInput(BaseModel):
    decision: Literal["approve", "reject"]


@router.post("/ai/tasks/{task_id}/approvals/{approval_id}")
async def decide(
    task_id: uuid.UUID,
    approval_id: uuid.UUID,
    data: DecisionInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    result = await aaee.proxy(
        settings,
        principal,
        "POST",
        f"/v1/tasks/{task_id}/approvals/{approval_id}",
        json=data.model_dump(),
    )
    audit(db, principal, f"ai.approval.{data.decision}", "ai_task", str(task_id))
    await db.commit()
    return result


class FeedbackInput(BaseModel):
    accepted: bool
    regression: bool = False
    comment: str = Field(default="", max_length=1_000)


@router.post("/ai/tasks/{task_id}/feedback", status_code=status.HTTP_201_CREATED)
async def feedback(
    task_id: uuid.UUID,
    data: FeedbackInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    await _visible(
        db, principal, await aaee.proxy(settings, principal, "GET", f"/v1/tasks/{task_id}")
    )
    return await aaee.proxy(
        settings, principal, "POST", f"/v1/tasks/{task_id}/feedback", json=data.model_dump()
    )


class PlanInput(BaseModel):
    task_type: str = Field(max_length=40)
    task_description: str = Field(min_length=1, max_length=4_000)
    development_phase: str | None = Field(default=None, max_length=24)
    project_id: uuid.UUID | None = None


@router.post("/ai/plan")
async def preview_plan(
    data: PlanInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Explains which strategy and model AAEE would choose. Nothing runs and no budget is reserved."""
    if data.project_id:
        await project_access(db, data.project_id, principal)
    body = data.model_dump(mode="json", exclude_none=True)
    return await aaee.proxy(
        settings, principal, "POST", "/v1/plan", json=body, project_id=data.project_id
    )


# -- CDE workspace agent tasks -----------------------------------------------------------------

AGENT_TASK_TYPES = Literal[
    "incremental_code_edit", "debugging", "test_generation", "documentation", "security_review"
]


class ContextFile(BaseModel):
    path: str = Field(min_length=1, max_length=400)
    content: str = Field(max_length=200_000)


class AgentTaskInput(BaseModel):
    instruction: str = Field(min_length=3, max_length=8_000)
    task_type: AGENT_TASK_TYPES = "incremental_code_edit"
    files: list[ContextFile] = Field(default_factory=list, max_length=20)
    allowed_paths: list[str] = Field(default_factory=list, max_length=20)


class Evidence(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal[
        "typecheck",
        "lint",
        "unit_tests",
        "build",
        "e2e",
        "api_tests",
        "integration_tests",
        "migrations",
        "format",
        "review",
    ]
    status: Literal["passed", "failed", "skipped"]
    output: str = Field(default="", max_length=20_000)


class ChecksInput(BaseModel):
    items: list[Evidence] = Field(min_length=1, max_length=20)
    retry: bool = True


def agent_task_view(row: WorkspaceAgentTask) -> dict:
    return {
        "id": str(row.id),
        "workspace_id": str(row.workspace_id),
        "aaee_task_id": row.aaee_task_id,
        "task_type": row.task_type,
        "instruction": row.instruction,
        "status": row.status,
        "strategy": row.strategy,
        "model": row.model,
        "phase": row.phase,
        "cost_usd": round(row.cost_usd or 0, 6),
        "proposal": row.proposal,
        "detail": row.detail,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _absorb(row: WorkspaceAgentTask, task: dict) -> None:
    action = task.get("next_action") or {}
    row.aaee_task_id = task["id"]
    row.status = task["status"]
    row.strategy = task.get("strategy") or action.get("strategy")
    row.model = task.get("model") or action.get("model")
    row.phase = task.get("development_phase")
    row.cost_usd = task.get("total_cost_usd", 0)
    if task["status"] == "awaiting_validation" and action.get("type") == "result":
        output = action.get("output") or {}
        row.proposal = {
            "execution_id": action["execution_id"],
            "files": [{"path": p, "content": c} for p, c in (output.get("files") or {}).items()],
            "summary": output.get("summary") or "",
            "content": output.get("content"),
            "checks": action.get("validate"),
        }
        row.detail = "Review the proposed changes, apply them in your workspace, run the checks, and report the results."
    elif task["status"] == "completed":
        output = (task.get("result") or {}).get("output") or {}
        files = output.get("files") or {}
        row.proposal = {
            **(row.proposal or {}),
            "files": [{"path": p, "content": c} for p, c in files.items()]
            or (row.proposal or {}).get("files", []),
            "content": output.get("content"),
            "summary": output.get("summary") or (row.proposal or {}).get("summary", ""),
        }
        row.detail = "Completed." if not files else "Completed: your checks passed."
    else:
        row.detail = (action.get("reason") or task["status"].replace("_", " "))[:500]
    row.updated_at = datetime.now(UTC)


@router.get("/workspaces/{workspace_id}/agent-tasks")
async def list_agent_tasks(
    workspace_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> list[dict]:
    await tenant_workspace(db, workspace_id, principal)
    rows = await db.scalars(
        select(WorkspaceAgentTask)
        .where(WorkspaceAgentTask.workspace_id == workspace_id)
        .order_by(WorkspaceAgentTask.created_at.desc())
        .limit(50)
    )
    return [agent_task_view(r) for r in rows]


@router.post("/workspaces/{workspace_id}/agent-tasks", status_code=status.HTTP_201_CREATED)
async def create_agent_task(
    workspace_id: uuid.UUID,
    data: AgentTaskInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    if principal.role == "viewer":
        raise HTTPException(status_code=403, detail="Viewers cannot start AI tasks")
    workspace = await tenant_workspace(db, workspace_id, principal)
    row = WorkspaceAgentTask(
        workspace_id=workspace.id,
        organization_id=principal.organization_id,
        requested_by=principal.user_id,
        task_type=data.task_type,
        instruction=data.instruction,
    )
    db.add(row)
    await db.flush()
    body = {
        "task_type": data.task_type,
        "task_description": data.instruction,
        "workspace_id": str(workspace.id),
        "input_artifacts": [f.model_dump() for f in data.files],
        "allowed_paths": data.allowed_paths,
        # AAEE proposes file contents only. It never runs commands in, or connects to, the workspace.
        "execution_environment": {"kind": "cde_workspace", "workspace_id": str(workspace.id)},
        "permitted_actions": ["write_files"] if data.task_type != "documentation" else [],
        "context": {"template": workspace.template},
        "idempotency_key": f"cde:{row.id}",
    }
    try:
        task = await aaee.submit(settings, principal, body, wait=90, service="cde")
    except aaee.Unavailable as exc:
        await db.rollback()
        raise HTTPException(
            status_code=503, detail="The AI execution engine is unavailable. Try again shortly."
        ) from exc
    _absorb(row, task)
    audit(db, principal, "workspace.agent_task.create", "workspace", str(workspace.id))
    await db.commit()
    return agent_task_view(row)


async def _agent_task(
    db: AsyncSession, principal: Principal, workspace_id: uuid.UUID, task_id: uuid.UUID
) -> WorkspaceAgentTask:
    await tenant_workspace(db, workspace_id, principal)
    row = await db.get(WorkspaceAgentTask, task_id)
    if not row or row.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent task not found")
    return row


@router.get("/workspaces/{workspace_id}/agent-tasks/{task_id}")
async def get_agent_task(
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    row = await _agent_task(db, principal, workspace_id, task_id)
    if row.aaee_task_id and row.status in {"queued", "running"}:
        _absorb(
            row,
            await aaee.proxy(
                settings, principal, "GET", f"/v1/tasks/{row.aaee_task_id}", service="cde"
            ),
        )
        await db.commit()
    return agent_task_view(row)


@router.post("/workspaces/{workspace_id}/agent-tasks/{task_id}/checks")
async def report_agent_checks(
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    data: ChecksInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    """The user applied the proposal in their workspace and ran the checks; AAEE learns from the outcome."""
    row = await _agent_task(db, principal, workspace_id, task_id)
    execution_id = (row.proposal or {}).get("execution_id")
    if row.status != "awaiting_validation" or not execution_id:
        raise HTTPException(status_code=409, detail="This task is not waiting for check results")
    report = {
        "items": [item.model_dump() for item in data.items],
        "output_files": (row.proposal or {}).get("files", [])[:400],
        "changed_files": [f["path"] for f in (row.proposal or {}).get("files", [])][:500],
        "continue_automatically": data.retry,
    }
    try:
        task = await aaee.validate(
            settings, principal, {"id": row.aaee_task_id}, execution_id, report, wait=90
        )
    except aaee.Unavailable as exc:
        raise HTTPException(
            status_code=503, detail="The AI execution engine is unavailable. Try again shortly."
        ) from exc
    _absorb(row, task)
    await db.commit()
    return agent_task_view(row)


@router.post("/workspaces/{workspace_id}/agent-tasks/{task_id}/discard")
async def discard_agent_task(
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(get_principal),
    settings: Settings = Depends(get_settings),
) -> dict:
    row = await _agent_task(db, principal, workspace_id, task_id)
    if row.aaee_task_id and row.status not in {"completed", "failed", "cancelled"}:
        try:
            await aaee.call(
                settings, principal, "POST", f"/v1/tasks/{row.aaee_task_id}/cancel", service="cde"
            )
        except aaee.Unavailable as exc:
            raise HTTPException(
                status_code=503, detail="The AI execution engine is unavailable. Try again shortly."
            ) from exc
    row.status = "cancelled"
    row.detail = "Discarded."
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return agent_task_view(row)


# -- administration ------------------------------------------------------------------------------

Scope = Literal["organization", "platform"]


@router.get("/ai/admin/analytics")
async def admin_analytics(
    scope: Scope = "organization",
    days: int = Query(default=30, ge=1, le=365),
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    return await aaee.proxy(
        settings, principal, "GET", "/v1/admin/analytics", params={"scope": scope, "days": days}
    )


@router.get("/ai/admin/performance")
async def admin_performance(
    scope: Scope = "organization",
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    return await aaee.proxy(
        settings, principal, "GET", "/v1/admin/performance", params={"scope": scope}
    )


@router.get("/ai/admin/budgets")
async def admin_budgets(
    principal: Principal = Depends(require_admin), settings: Settings = Depends(get_settings)
) -> dict:
    return await aaee.proxy(settings, principal, "GET", "/v1/admin/budgets")


class AaeeBudgetInput(BaseModel):
    scope: Literal["platform", "user"]
    scope_id: str = Field(default="default", max_length=36)
    limit_usd: float = Field(ge=0, le=1_000_000)
    hard_limit: bool = True
    alert_threshold: float = Field(default=0.8, gt=0, le=1)


@router.put("/ai/admin/budgets")
async def put_admin_budget(
    data: AaeeBudgetInput,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    result = await aaee.proxy(
        settings, principal, "PUT", "/v1/admin/budgets", json=data.model_dump()
    )
    audit(db, principal, "ai.budget.update", data.scope, data.scope_id)
    await db.commit()
    return result


@router.get("/ai/admin/audit")
async def admin_audit(
    scope: Scope = "organization",
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> list:
    return await aaee.proxy(settings, principal, "GET", "/v1/admin/audit", params={"scope": scope})


@router.get("/ai/admin/models")
async def admin_models(
    principal: Principal = Depends(require_admin), settings: Settings = Depends(get_settings)
) -> list:
    return await aaee.proxy(settings, principal, "GET", "/v1/admin/models")


@router.put("/ai/admin/models/{provider}/{model_id:path}")
async def put_admin_model(
    provider: str,
    model_id: str,
    data: dict,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    result = await aaee.proxy(
        settings, principal, "PUT", f"/v1/admin/models/{provider}/{model_id}", json=data
    )
    audit(db, principal, "ai.model_policy.update", "model", f"{provider}/{model_id}"[:64])
    await db.commit()
    return result


@router.get("/ai/admin/policies")
async def admin_policies(
    principal: Principal = Depends(require_admin), settings: Settings = Depends(get_settings)
) -> list:
    return await aaee.proxy(settings, principal, "GET", "/v1/admin/policies")


@router.post("/ai/admin/policies", status_code=status.HTTP_201_CREATED)
async def create_policy(
    data: dict,
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    return await aaee.proxy(settings, principal, "POST", "/v1/admin/policies", json=data)


@router.post("/ai/admin/policies/{version}/status")
async def policy_status(
    version: int,
    data: dict,
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    return await aaee.proxy(
        settings, principal, "POST", f"/v1/admin/policies/{version}/status", json=data
    )


@router.get("/ai/admin/benchmarks")
async def list_benchmarks(
    principal: Principal = Depends(require_admin), settings: Settings = Depends(get_settings)
) -> list:
    return await aaee.proxy(settings, principal, "GET", "/v1/admin/benchmarks")


@router.post("/ai/admin/benchmarks", status_code=status.HTTP_202_ACCEPTED)
async def start_benchmark(
    data: dict,
    principal: Principal = Depends(require_admin),
    settings: Settings = Depends(get_settings),
) -> dict:
    return await aaee.proxy(settings, principal, "POST", "/v1/admin/benchmarks", json=data)
