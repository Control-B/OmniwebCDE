from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AAEE_", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./aaee.db"
    data_dir: str = "./.aaee"
    redis_url: str = ""

    # Callers (the Omniweb control plane) sign short-lived tokens with this secret.
    service_secret: str = Field(default="", repr=False)
    # AAEE calls the model gateway with tokens signed by the gateway's service secret.
    gateway_url: str = "http://127.0.0.1:8020"
    gateway_secret: str = Field(default="", repr=False)
    gateway_timeout_seconds: float = 150
    registry_cache_seconds: float = 30

    # Security scanners used by the validation engine when present on PATH or in scanner_path.
    scanner_path: str = str(Path.home() / "go" / "bin")

    # Rate limiting for task submission, per tenant.
    tasks_per_minute: int = 120

    # Budgets owned by AAEE. Organization and project limits come from the gateway.
    platform_monthly_budget_usd: float = 10_000
    user_monthly_budget_usd: float = 25
    default_task_budget_usd: float = 2.0
    default_execution_ceiling_usd: float = 1.0
    alert_threshold: float = 0.8

    # Customer billing: platform-billed usage can carry a markup; BYOK usage is never an
    # Omniweb provider expense.
    platform_markup: float = 0.0
    byok_platform_fee_usd_per_execution: float = 0.0

    max_artifact_bytes: int = 5_000_000
    max_task_artifact_bytes: int = 20_000_000

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
