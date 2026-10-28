import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Task(Base):
    """A unit of work submitted by a caller. All policy-relevant fields are server-resolved."""

    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID | None]
    project_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(64), index=True)
    caller: Mapped[str] = mapped_column(String(32), default="control-plane")
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    task_type: Mapped[str] = mapped_column(String(40), index=True)
    description: Mapped[str] = mapped_column(Text)
    spec: Mapped[dict] = mapped_column(JSON)  # the resolved TaskSpec
    complexity: Mapped[str] = mapped_column(String(16))
    risk_level: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    policy_version: Mapped[int] = mapped_column(Integer, default=1)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    next_action: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts_used: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    retry_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    overage_approved_usd: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Execution(Base):
    """One attempt at a task with one strategy. Also the task-level usage ledger row."""

    __tablename__ = "executions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID | None]
    attempt: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(String(24), default="generate")  # generate | repair | classify | review
    strategy: Mapped[str] = mapped_column(String(24), index=True)
    tool: Mapped[str | None] = mapped_column(String(80))
    provider: Mapped[str | None] = mapped_column(String(40), index=True)
    model_id: Mapped[str | None] = mapped_column(String(200), index=True)
    model_family: Mapped[str | None] = mapped_column(String(40))
    billing_model: Mapped[str] = mapped_column(String(16), default="none")  # platform | customer | none
    status: Mapped[str] = mapped_column(String(24), default="planned", index=True)
    validation: Mapped[str] = mapped_column(String(16), default="pending")  # pending | passed | failed | not_required
    error_category: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(String(500))
    escalation_reason: Mapped[str | None] = mapped_column(String(500))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_usage: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    inference_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    infra_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    actual_reported_cost_usd: Mapped[float | None] = mapped_column(Float)
    provider_cost_usd: Mapped[float] = mapped_column(Float, default=0)  # Omniweb's own provider expense
    customer_billable_usd: Mapped[float] = mapped_column(Float, default=0)
    reserved_usd: Mapped[float] = mapped_column(Float, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    request_id: Mapped[str | None] = mapped_column(String(64))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    output_hash: Mapped[str | None] = mapped_column(String(64))
    failure_fingerprint: Mapped[str | None] = mapped_column(String(64))
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    candidate: Mapped[dict] = mapped_column(JSON, default=dict)
    benchmark: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    """Idempotent usage reports. The unique key prevents double charging on retries."""

    __tablename__ = "usage_events"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id"), index=True)
    source: Mapped[str] = mapped_column(String(24))  # gateway | tool
    billing_model: Mapped[str] = mapped_column(String(16), default="platform")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    reported_cost_usd: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ValidationEvidence(Base):
    __tablename__ = "validation_evidence"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    submitted_by: Mapped[str] = mapped_column(String(32))  # caller | engine
    criteria: Mapped[dict] = mapped_column(JSON)
    items: Mapped[list] = mapped_column(JSON)
    passed: Mapped[bool] = mapped_column(Boolean)
    summary: Mapped[str] = mapped_column(String(1000), default="")
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(80))  # budget_overage | sensitive_action:<action> | human_review
    status: Mapped[str] = mapped_column(String(16), default="pending")
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    plan_digest: Mapped[str] = mapped_column(String(64))
    candidate: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0)
    requested_amount_usd: Mapped[float] = mapped_column(Float, default=0)
    decided_by: Mapped[uuid.UUID | None]
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Budget(Base):
    """AAEE-owned limits: platform, user, and per-tenant overrides. Organization and project
    limits are read from the model gateway."""

    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("scope", "scope_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    scope: Mapped[str] = mapped_column(String(24))  # platform | user | task_default | execution_ceiling
    scope_id: Mapped[str] = mapped_column(String(80))
    limit_usd: Mapped[float] = mapped_column(Float)
    hard_limit: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_threshold: Mapped[float] = mapped_column(Float, default=0.8)
    updated_by: Mapped[uuid.UUID | None]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class BudgetCounter(Base):
    """Locked during reservations so concurrent tasks cannot overspend a shared budget."""

    __tablename__ = "budget_counters"
    __table_args__ = (UniqueConstraint("scope", "scope_id", "period"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(24))
    scope_id: Mapped[str] = mapped_column(String(80))
    period: Mapped[str] = mapped_column(String(16))  # YYYY-MM or "lifetime"
    reserved_usd: Mapped[float] = mapped_column(Float, default=0)
    # Spend that does not pass through the gateway (engine and caller-side tools).
    external_spent_usd: Mapped[float] = mapped_column(Float, default=0)
    # All spend recorded by AAEE, used for AAEE-owned scopes.
    spent_usd: Mapped[float] = mapped_column(Float, default=0)
    version: Mapped[int] = mapped_column(Integer, default=0)


class BudgetReservation(Base):
    __tablename__ = "budget_reservations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    amount_usd: Mapped[float] = mapped_column(Float)
    scopes: Mapped[list] = mapped_column(JSON)  # [[scope, scope_id, period], ...]
    gateway_routed: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="held")  # held | committed | released
    actual_usd: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"
    __table_args__ = (UniqueConstraint("scope", "scope_id", "period", "kind"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    scope: Mapped[str] = mapped_column(String(24))
    scope_id: Mapped[str] = mapped_column(String(80))
    period: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))  # soft | exhausted
    message: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ModelPolicy(Base):
    """Administrative overlay on the gateway's discovered registry."""

    __tablename__ = "model_policies"
    __table_args__ = (UniqueConstraint("scope", "provider", "model_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(40), default="platform")  # platform | tenant id
    provider: Mapped[str] = mapped_column(String(40))
    model_id: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    family: Mapped[str | None] = mapped_column(String(40))
    hosting_mode: Mapped[str | None] = mapped_column(String(32))
    validated_input_usd_per_mtok: Mapped[float | None] = mapped_column(Float)
    validated_output_usd_per_mtok: Mapped[float | None] = mapped_column(Float)
    validated_cached_usd_per_mtok: Mapped[float | None] = mapped_column(Float)
    infra_usd_per_mtok: Mapped[float | None] = mapped_column(Float)
    rate_limit_rpm: Mapped[int | None] = mapped_column(Integer)
    capabilities_add: Mapped[list] = mapped_column(JSON, default=list)
    capabilities_remove: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(String(500), default="")
    validated_by: Mapped[uuid.UUID | None]
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class RoutingPolicy(Base):
    __tablename__ = "routing_policies"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | active | shadow | experiment | retired
    traffic_percent: Mapped[float] = mapped_column(Float, default=0)
    config: Mapped[dict] = mapped_column(JSON)
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class FileLease(Base):
    """Prevents two agents from modifying the same files of a project at the same time."""

    __tablename__ = "file_leases"
    __table_args__ = (UniqueConstraint("tenant_id", "resource", "path"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    resource: Mapped[str] = mapped_column(String(80))  # project or workspace id
    path: Mapped[str] = mapped_column(String(400))
    execution_id: Mapped[uuid.UUID] = mapped_column(index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskEvent(Base):
    __tablename__ = "task_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(String(24))  # input | output | evidence | diagnostic
    path: Mapped[str] = mapped_column(String(400), default="")
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID | None]
    accepted: Mapped[bool] = mapped_column(Boolean)
    regression: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    suite: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="running")
    models: Mapped[list] = mapped_column(JSON, default=list)
    results: Mapped[list] = mapped_column(JSON, default=list)
    budget_usd: Mapped[float] = mapped_column(Float)
    spent_usd: Mapped[float] = mapped_column(Float, default=0)
    started_by: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(60), index=True)
    target: Mapped[str] = mapped_column(String(200), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
