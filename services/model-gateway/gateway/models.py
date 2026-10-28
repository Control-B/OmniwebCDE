import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ProviderCredential(Base):
    """Customer-supplied provider keys. Platform keys come from the gateway environment."""

    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("organization_id", "provider"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(index=True)
    provider: Mapped[str] = mapped_column(String(32))
    encrypted_key: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(300), default="")
    key_fingerprint: Mapped[str] = mapped_column(String(16), default="")
    created_by: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ModelEntry(Base):
    __tablename__ = "model_registry"
    __table_args__ = (UniqueConstraint("provider", "model_id", "scope"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    model_id: Mapped[str] = mapped_column(String(200))
    # "platform" or an organization id for models discovered with a customer key.
    scope: Mapped[str] = mapped_column(String(40), default="platform", index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    context_window: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int | None] = mapped_column(Integer)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_structured_output: Mapped[bool] = mapped_column(Boolean, default=False)
    input_usd_per_mtok: Mapped[float | None] = mapped_column(Float)
    output_usd_per_mtok: Mapped[float | None] = mapped_column(Float)
    cached_input_usd_per_mtok: Mapped[float | None] = mapped_column(Float)
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    routable: Mapped[bool] = mapped_column(Boolean, default=True)
    deprecated: Mapped[bool] = mapped_column(Boolean, default=False)
    pricing_source: Mapped[str] = mapped_column(String(32), default="unknown")
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_id: Mapped[uuid.UUID | None]
    project_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    agent: Mapped[str] = mapped_column(String(64), default="assistant")
    provider: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(200))
    tier: Mapped[str] = mapped_column(String(24))
    billing_model: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("organization_id", "scope", "scope_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # "organization_monthly" or "project"
    scope: Mapped[str] = mapped_column(String(32))
    scope_id: Mapped[str] = mapped_column(String(40))
    limit_usd: Mapped[float] = mapped_column(Float)
    hard_limit: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_threshold: Mapped[float] = mapped_column(Float, default=0.8)


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"
    __table_args__ = (UniqueConstraint("budget_id", "period", "kind"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    budget_id: Mapped[uuid.UUID] = mapped_column(index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(index=True)
    period: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RoutingPreference(Base):
    __tablename__ = "routing_preferences"
    __table_args__ = (UniqueConstraint("organization_id", "scope_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # "organization" or a project id
    scope_id: Mapped[str] = mapped_column(String(40))
    default_tier: Mapped[str] = mapped_column(String(24), default="standard")
    allowed_providers: Mapped[list[str]] = mapped_column(JSON, default=list)
    pinned_models: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    max_escalations: Mapped[int | None] = mapped_column(Integer)
