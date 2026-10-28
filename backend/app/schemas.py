import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, SecretStr, field_validator

from .models import WorkspaceState


class Principal(BaseModel):
    user_id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    role: str
    display_name: str = ""
    auth_mode: str = "development"


class CloudConnectionCreate(BaseModel):
    label: str = Field(min_length=2, max_length=100)
    token: SecretStr


class CloudConnectionView(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    provider: str
    label: str
    token_fingerprint: str
    provider_account_id: str | None
    healthy: bool
    last_checked_at: datetime | None


class Region(BaseModel):
    slug: str
    name: str
    available: bool


class Size(BaseModel):
    slug: str
    vcpus: int
    memory_mb: int
    disk_gb: int
    monthly_usd: Decimal
    available: bool = True


class WorkspaceCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,31}$")
    cloud_connection_id: uuid.UUID
    region: str
    size: str
    image: str = "ubuntu-24-04-x64"
    template: str = "full-stack"
    idempotency_key: str = Field(min_length=8, max_length=100)
    approved_estimated_monthly_usd: Decimal = Field(gt=0)

    @field_validator("region", "size", "image", "template")
    @classmethod
    def safe_slug(cls, value: str) -> str:
        if not value.replace("-", "").isalnum():
            raise ValueError("must contain only letters, digits, and hyphens")
        return value


class WorkspaceView(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    region: str
    size: str
    image: str
    template: str
    state: WorkspaceState
    estimated_monthly_usd: Decimal
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime


class WorkspaceEventView(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    from_state: WorkspaceState | None
    to_state: WorkspaceState
    reason: str
    created_at: datetime


class DashboardSummary(BaseModel):
    total: int
    running: int
    stopped: int
    failed: int
    cloud_connections: int
    estimated_monthly_usd: Decimal


class AccessLink(BaseModel):
    url: str
    expires_in_seconds: int
    kind: str
