import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import performance_evaluator, routing_policy, telemetry
from .config import Settings, get_settings
from .contracts import SERVER_ONLY_FIELDS, ApprovalDecision, FeedbackInput, TaskRequest, UsageReport, ValidationReport
from .database import SessionLocal, engine, get_db
from .engine import ADMIN_APPROVALS, TERMINAL, Engine
from .execution_planner import PlanContext, plan
from .inference_gateway import GatewayError, HttpGateway
from .model_registry import Registry
from .models import Approval, Base, Execution, Feedback, ModelPolicy, RoutingPolicy, Task, TaskEvent
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
    app.state.engine = Engine(settings, app.state.gateway, app.state.registry)
    resumed = await app.state.engine.resume()
    if resumed:
        logger.info("Resumed %d tasks", resumed)
    yield
    running = list(app.state.engine.running.values())
    for task in running:
        task.cancel()
    # Cancelled tasks must unwind their transactions before the pool goes away,
    # otherwise SQLite keeps the write lock held by an orphaned connection.
    await asyncio.gather(*running, return_exceptions=True)
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
    ctx = PlanContext(budget_available_usd=available, execution_ceiling_usd=settings.default_execution_ceiling_usd, production=settings.is_production)
    artifacts = {a.path: a.content or "" for a in body.input_artifacts}
    result = plan(spec, models, policy, await performance_evaluator.load(db), ctx, artifacts)
    await db.commit()
    return {"spec": spec.model_dump(mode="json"), "plan": result, "policy_version": active.version}


class ModelPolicyInput(BaseModel):
    scope: Literal["platform", "tenant"] = "platform"
    enabled: bool = True
    priority: int = Field(default=0, ge=-100, le=100)
    family: Literal["gpt_oss", "grok", "hosted", "development"] | None = None
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
    provider: str,
    model_id: str,
    body: ModelPolicyInput,
    request: Request,
    identity: Caller = Depends(tenant_admin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    models = {m.key: m for m in await registry(request).load(db, identity)}
    model = models.get(f"{provider}/{model_id}")
    if not model:
        raise HTTPException(status_code=404, detail="Model is not in the gateway registry for this organization")
    if body.scope == "platform" and not identity.platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator access required for platform-wide model policy")
    if (
        body.scope == "tenant"
        and model.billing_model != "customer"
        and any(v is not None for v in (body.validated_input_usd_per_mtok, body.validated_output_usd_per_mtok, body.infra_usd_per_mtok))
    ):
        raise HTTPException(status_code=403, detail="Organizations can only validate pricing for models on their own provider keys")
    if (body.validated_input_usd_per_mtok is None) != (body.validated_output_usd_per_mtok is None):
        raise HTTPException(status_code=422, detail="Validated pricing needs both input and output prices")
    scope = "platform" if body.scope == "platform" else str(identity.tenant_id)
    overlay = await db.scalar(select(ModelPolicy).where(ModelPolicy.scope == scope, ModelPolicy.provider == provider, ModelPolicy.model_id == model_id))
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
    return {
        "version": policy.version,
        "status": policy.status,
        "traffic_percent": policy.traffic_percent,
        "notes": policy.notes,
        "config": policy.config,
        "created_at": policy.created_at.isoformat(),
    }


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
    policy = RoutingPolicy(version=(latest.version if latest else 0) + 1, status="draft", config=config, notes=body.notes, created_by=identity.user_id)
    db.add(policy)
    await audit(db, identity, "routing_policy.create", f"v{policy.version}", {"notes": body.notes})
    await db.commit()
    return policy_view(policy)


@app.post("/v1/admin/policies/{version}/status")
async def set_policy_status(version: int, body: PolicyStatus, identity: Caller = Depends(platform_admin), db: AsyncSession = Depends(get_db)) -> dict:
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


# Tasks -----------------------------------------------------------------------------------


def engine_of(request: Request) -> Engine:
    return request.app.state.engine


async def owned_task(db: AsyncSession, identity: Caller, task_id: uuid.UUID) -> Task:
    task = await db.get(Task, task_id)
    # Tasks are tenant-scoped; another tenant's task is indistinguishable from a missing one.
    if not task or task.tenant_id != identity.tenant_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


async def task_view(db: AsyncSession, task: Task, detail: bool = True) -> dict:
    view = {
        "id": str(task.id),
        "task_type": task.task_type,
        "status": task.status,
        "complexity": task.complexity,
        "risk_level": task.risk_level,
        "development_phase": task.spec.get("development_phase"),
        "project_id": str(task.project_id) if task.project_id else None,
        "workspace_id": task.workspace_id,
        "policy_version": task.policy_version,
        "attempts": task.attempts_used,
        "estimated_cost_usd": round(task.estimated_cost_usd, 6),
        "total_cost_usd": round(task.total_cost_usd, 6),
        "retry_cost_usd": round(task.retry_cost_usd, 6),
        "strategy": (task.plan.get("chosen") or {}).get("strategy"),
        "model": (task.plan.get("chosen") or {}).get("key"),
        "next_action": task.next_action,
        "created_at": task.created_at.isoformat(),
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "description": task.description[:300],
    }
    if not detail:
        return view
    executions = list(await db.scalars(select(Execution).where(Execution.task_id == task.id).order_by(Execution.attempt)))
    approvals = list(await db.scalars(select(Approval).where(Approval.task_id == task.id).order_by(Approval.created_at)))
    view.update(
        {
            "spec": {
                k: task.spec.get(k)
                for k in (
                    "quality_threshold",
                    "maximum_budget_usd",
                    "maximum_attempts",
                    "risk_reasons",
                    "approval_requirements",
                    "allowed_paths",
                    "required_capabilities",
                )
            },
            "plan": task.plan,
            "result": task.result,
            "diagnostics": {k: v for k, v in task.diagnostics.items() if k not in {"repair_notes", "caller_notes"}},
            "executions": [
                {
                    "id": str(e.id),
                    "attempt": e.attempt,
                    "purpose": e.purpose,
                    "strategy": e.strategy,
                    "tool": e.tool,
                    "model": (e.candidate or {}).get("key"),
                    "status": e.status,
                    "validation": e.validation,
                    "error_category": e.error_category,
                    "escalation_reason": e.escalation_reason,
                    "billing_model": e.billing_model,
                    "input_tokens": e.input_tokens,
                    "output_tokens": e.output_tokens,
                    "cached_tokens": e.cached_tokens,
                    "estimated_cost_usd": round(e.estimated_cost_usd, 6),
                    "total_cost_usd": round(e.total_cost_usd, 6),
                    "provider_cost_usd": round(e.provider_cost_usd, 6),
                    "customer_billable_usd": round(e.customer_billable_usd, 6),
                    "duration_ms": e.duration_ms,
                }
                for e in executions
            ],
            "approvals": [
                {
                    "id": str(a.id),
                    "kind": a.kind,
                    "status": a.status,
                    "reasons": a.reasons,
                    "estimated_cost_usd": a.estimated_cost_usd,
                    "requested_amount_usd": a.requested_amount_usd,
                    "candidate": (a.candidate or {}).get("key"),
                }
                for a in approvals
            ],
        }
    )
    return view


async def wait_for(task_id: uuid.UUID, seconds: float) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        async with SessionLocal() as db:
            status = await db.scalar(select(Task.status).where(Task.id == task_id))
        if status not in {"queued", "running"}:
            return
        await asyncio.sleep(0.05)


@app.post("/v1/tasks", status_code=201)
async def create_task(
    request: Request,
    raw: dict = Body(...),
    wait: float = Query(default=30, ge=0, le=300),
    identity: Caller = Depends(caller),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    body = parse_task_request(raw)
    if not await request.app.state.rate_limiter.check(f"tasks:{identity.tenant_id}", settings.tasks_per_minute):
        raise HTTPException(status_code=429, detail="Too many AI tasks for this organization; try again shortly")
    task, created = await engine_of(request).submit(db, identity, body)
    await db.commit()
    if created:
        engine_of(request).schedule(task.id)
    if wait:
        await wait_for(task.id, wait)
    async with SessionLocal() as fresh:
        return await task_view(fresh, await fresh.get(Task, task.id))


@app.get("/v1/tasks")
async def list_tasks(
    status: str | None = None,
    project_id: uuid.UUID | None = None,
    workspace_id: str | None = None,
    limit: int = Query(default=50, le=200),
    identity: Caller = Depends(caller),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = select(Task).where(Task.tenant_id == identity.tenant_id).order_by(Task.created_at.desc()).limit(limit)
    if status:
        query = query.where(Task.status == status)
    if project_id:
        query = query.where(Task.project_id == project_id)
    if workspace_id:
        query = query.where(Task.workspace_id == workspace_id)
    return [await task_view(db, t, detail=False) for t in await db.scalars(query)]


@app.get("/v1/tasks/{task_id}")
async def get_task(task_id: uuid.UUID, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db)) -> dict:
    return await task_view(db, await owned_task(db, identity, task_id))


@app.get("/v1/tasks/{task_id}/events")
async def task_events(task_id: uuid.UUID, request: Request, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db)):
    await owned_task(db, identity, task_id)
    await db.close()  # do not hold a transaction (and SQLite's write lock) for the life of the stream
    last = int(request.headers.get("last-event-id") or request.query_params.get("after") or 0)

    async def stream():
        nonlocal last
        idle = 0
        while idle < 600:
            async with SessionLocal() as session:
                rows = list(await session.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id, TaskEvent.id > last).order_by(TaskEvent.id)))
                status = await session.scalar(select(Task.status).where(Task.id == task_id))
            for row in rows:
                last = row.id
                yield f"id: {row.id}\nevent: {row.kind}\ndata: {json.dumps({**row.data, 'kind': row.kind, 'at': row.created_at.isoformat()})}\n\n"
            if status in TERMINAL and not rows:
                yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
                return
            if await request.is_disconnected():
                return
            idle = 0 if rows else idle + 1
            if not rows:
                yield ": keep-alive\n\n" if idle % 30 == 0 else ""
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ValidationInput(BaseModel):
    execution_id: uuid.UUID
    report: ValidationReport


@app.post("/v1/tasks/{task_id}/validation")
async def submit_validation(
    task_id: uuid.UUID, body: ValidationInput, request: Request, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db)
) -> dict:
    task = await owned_task(db, identity, task_id)
    execution = await db.get(Execution, body.execution_id)
    if not execution or execution.task_id != task.id:
        raise HTTPException(status_code=404, detail="Execution not found")
    if execution.status not in {"awaiting_validation", "dispatched"} or task.status not in {"awaiting_validation", "awaiting_caller"}:
        raise HTTPException(status_code=409, detail=f"Execution is {execution.status}; validation is not expected")
    await engine_of(request).submit_validation(db, task, execution, body.report)
    async with SessionLocal() as fresh:
        return await task_view(fresh, await fresh.get(Task, task_id))


@app.post("/v1/tasks/{task_id}/executions/{execution_id}/usage")
async def report_usage(
    task_id: uuid.UUID, execution_id: uuid.UUID, body: UsageReport, request: Request, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db)
) -> dict:
    task = await owned_task(db, identity, task_id)
    execution = await db.get(Execution, execution_id)
    if not execution or execution.task_id != task.id:
        raise HTTPException(status_code=404, detail="Execution not found")
    recorded = await engine_of(request).report_usage(db, task, execution, body)
    return {"recorded": recorded}


@app.post("/v1/tasks/{task_id}/approvals/{approval_id}")
async def decide_approval(
    task_id: uuid.UUID, approval_id: uuid.UUID, body: ApprovalDecision, request: Request, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db)
) -> dict:
    task = await owned_task(db, identity, task_id)
    approval = await db.get(Approval, approval_id)
    if not approval or approval.task_id != task.id:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"Approval is already {approval.status}")
    # Enforced here, not by model instructions: only organization administrators decide gates.
    if approval.kind.split(":", 1)[0] in ADMIN_APPROVALS and not identity.tenant_admin:
        raise HTTPException(status_code=403, detail="An organization owner or admin must decide this approval")
    await engine_of(request).approve(db, identity, task, approval, body.decision == "approve")
    await audit(db, identity, f"approval.{body.decision}", f"{task.id}:{approval.kind}")
    await db.commit()
    async with SessionLocal() as fresh:
        return await task_view(fresh, await fresh.get(Task, task_id))


@app.post("/v1/tasks/{task_id}/cancel")
async def cancel_task(task_id: uuid.UUID, request: Request, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db)) -> dict:
    task = await owned_task(db, identity, task_id)
    if task.status in TERMINAL:
        raise HTTPException(status_code=409, detail=f"Task is already {task.status}")
    await engine_of(request).cancel(db, task)
    async with SessionLocal() as fresh:
        return await task_view(fresh, await fresh.get(Task, task_id))


@app.post("/v1/tasks/{task_id}/feedback", status_code=201)
async def task_feedback(task_id: uuid.UUID, body: FeedbackInput, identity: Caller = Depends(caller), db: AsyncSession = Depends(get_db)) -> dict:
    task = await owned_task(db, identity, task_id)
    if task.status not in TERMINAL:
        raise HTTPException(status_code=409, detail="Feedback is accepted once the task has finished")
    # Stored for analytics and review only; it never edits routing policies or global statistics.
    db.add(
        Feedback(
            task_id=task.id,
            tenant_id=task.tenant_id,
            user_id=identity.user_id,
            accepted=body.accepted,
            regression=body.regression,
            comment=redact(body.comment),
        )
    )
    await db.commit()
    return {"recorded": True}
