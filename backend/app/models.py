import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class WorkspaceState(StrEnum):
    REQUESTED = "REQUESTED"
    VALIDATING = "VALIDATING"
    PROVISIONING = "PROVISIONING"
    BOOTSTRAPPING = "BOOTSTRAPPING"
    CONNECTING = "CONNECTING"
    READY = "READY"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    REBUILDING = "REBUILDING"
    DELETING = "DELETING"
    DELETED = "DELETED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    monthly_limit_usd: Mapped[float] = mapped_column(Numeric(10, 2), default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    oidc_subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(24), default="member")


class CloudConnection(Base):
    __tablename__ = "cloud_connections"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32), default="digitalocean")
    label: Mapped[str] = mapped_column(String(100))
    encrypted_token: Mapped[str] = mapped_column(Text)
    token_fingerprint: Mapped[str] = mapped_column(String(16))
    provider_account_id: Mapped[str | None] = mapped_column(String(100))
    healthy: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("organization_id", "idempotency_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    cloud_connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cloud_connections.id"))
    name: Mapped[str] = mapped_column(String(64))
    region: Mapped[str] = mapped_column(String(32))
    size: Mapped[str] = mapped_column(String(64))
    image: Mapped[str] = mapped_column(String(80), default="ubuntu-24-04-x64")
    template: Mapped[str] = mapped_column(String(80), default="full-stack")
    state: Mapped[WorkspaceState] = mapped_column(
        Enum(WorkspaceState, native_enum=False), default=WorkspaceState.REQUESTED, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(100))
    external_resource_id: Mapped[str | None] = mapped_column(String(100))
    provider_operation_id: Mapped[str | None] = mapped_column(String(100))
    coder_workspace_id: Mapped[str | None] = mapped_column(String(100))
    estimated_monthly_usd: Mapped[float] = mapped_column(Numeric(10, 2))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    events: Mapped[list["WorkspaceEvent"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceEvent(Base):
    __tablename__ = "workspace_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    from_state: Mapped[WorkspaceState | None] = mapped_column(
        Enum(WorkspaceState, native_enum=False)
    )
    to_state: Mapped[WorkspaceState] = mapped_column(Enum(WorkspaceState, native_enum=False))
    reason: Mapped[str] = mapped_column(String(255))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    workspace: Mapped[Workspace] = relationship(back_populates="events")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    template: Mapped[str] = mapped_column(String(40), default="react-web")
    stack: Mapped[list[str]] = mapped_column(JSON, default=list)
    generation_status: Mapped[str] = mapped_column(String(24), default="draft")
    deployment_status: Mapped[str] = mapped_column(String(24), default="not_deployed")
    github_repo: Mapped[str | None] = mapped_column(String(200))
    app_config: Mapped[dict] = mapped_column(JSON, default=dict)
    spec: Mapped[dict | None] = mapped_column(JSON)
    migrations: Mapped[list] = mapped_column(JSON, default=list)
    head_sha: Mapped[str | None] = mapped_column(String(40))
    preview_token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    last_build: Mapped[dict | None] = mapped_column(JSON)
    github_installation_id: Mapped[str | None] = mapped_column(String(40))
    github_default_branch: Mapped[str] = mapped_column(String(100), default="main")
    last_pushed_sha: Mapped[str | None] = mapped_column(String(40))
    last_pulled_sha: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class GenerationRun(Base):
    """One pass of the builder graph. `state` is saved after every node so runs resume after restarts."""

    __tablename__ = "generation_runs"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(24))
    instruction: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    checkpoint_sha: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Checkpoint(Base):
    __tablename__ = "checkpoints"
    __table_args__ = (UniqueConstraint("project_id", "sha"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    sha: Mapped[str] = mapped_column(String(40))
    parent_sha: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(300))
    author: Mapped[str] = mapped_column(String(16))
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="SET NULL")
    )
    restores_sha: Mapped[str | None] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(16), default="change")
    undo_of: Mapped[str | None] = mapped_column(String(40))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    spec: Mapped[dict | None] = mapped_column(JSON)
    migrations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Approval(Base):
    """A decision a person must make before an agent may continue (destructive migrations, deploys)."""

    __tablename__ = "approvals"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    summary: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_monthly_usd: Mapped[float | None] = mapped_column(Float)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generation_runs.id", ondelete="SET NULL")
    )
    requested_by: Mapped[str] = mapped_column(String(64))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Deployment(Base):
    __tablename__ = "deployments"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment: Mapped[str] = mapped_column(String(16))
    cloud_connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cloud_connections.id"))
    commit_sha: Mapped[str] = mapped_column(String(40))
    region: Mapped[str] = mapped_column(String(16), default="nyc")
    status: Mapped[str] = mapped_column(String(24), default="awaiting_approval")
    approval_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("approvals.id"))
    external_app_id: Mapped[str | None] = mapped_column(String(100))
    external_deployment_id: Mapped[str | None] = mapped_column(String(100))
    url: Mapped[str | None] = mapped_column(String(300))
    estimated_monthly_usd: Mapped[float] = mapped_column(Float, default=0)
    rollback_of: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("deployments.id"))
    app_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    log: Mapped[list] = mapped_column(JSON, default=list)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16), default="editor")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="Main")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    agent: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(240))
    tier: Mapped[str | None] = mapped_column(String(24))
    request_id: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    development_model: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class AgentExecution(Base):
    __tablename__ = "agent_executions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    agent: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(240))
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    detail: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[list] = mapped_column(JSON, default=list)
    aaee_task_id: Mapped[str | None] = mapped_column(String(40), index=True)
    strategy: Mapped[str | None] = mapped_column(String(24))
    phase: Mapped[str | None] = mapped_column(String(24))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceAgentTask(Base):
    """An AI task for a CDE workspace. AAEE proposes file edits; the user reviews and applies them.

    The model never runs commands in the workspace and never receives workspace credentials.
    """

    __tablename__ = "workspace_agent_tasks"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    aaee_task_id: Mapped[str | None] = mapped_column(String(40), index=True)
    task_type: Mapped[str] = mapped_column(String(40))
    instruction: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    strategy: Mapped[str | None] = mapped_column(String(24))
    model: Mapped[str | None] = mapped_column(String(240))
    phase: Mapped[str | None] = mapped_column(String(24))
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    proposal: Mapped[dict] = mapped_column(JSON, default=dict)
    detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


ADDED_COLUMNS = {
    "agent_executions": {
        "aaee_task_id": "VARCHAR(40)",
        "strategy": "VARCHAR(24)",
        "phase": "VARCHAR(24)",
    }
}


class ProjectEnvVar(Base):
    __tablename__ = "project_env_vars"
    __table_args__ = (UniqueConstraint("project_id", "environment", "key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    environment: Mapped[str] = mapped_column(String(16), default="development")
    key: Mapped[str] = mapped_column(String(128))
    encrypted_value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
