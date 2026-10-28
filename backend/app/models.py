import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class WorkspaceState(str, enum.Enum):
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
    encrypted_token: Mapped[str] = mapped_column(Text, repr=False)
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
