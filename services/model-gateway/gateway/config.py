from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="GATEWAY_", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./gateway.db"
    service_secret: str = Field(default="", repr=False)
    encryption_key: str = Field(default="", repr=False)
    mock_mode: bool = True

    # Platform-managed credentials. Customer-supplied keys are stored encrypted per organization.
    openai_api_key: str = Field(default="", repr=False)
    anthropic_api_key: str = Field(default="", repr=False)
    gemini_api_key: str = Field(default="", repr=False)
    openrouter_api_key: str = Field(default="", repr=False)
    openai_compatible_base_url: str = ""
    openai_compatible_api_key: str = Field(default="", repr=False)
    ollama_base_url: str = ""
    # OpenRouter publishes its catalog without a key, which keeps pricing data fresh even when
    # no OpenRouter key is configured. Such models are listed but not routable.
    openrouter_public_catalog: bool = True

    max_attempts: int = 3
    max_escalations: int = 1
    request_timeout_seconds: float = 120
    alert_threshold: float = 0.8
    default_monthly_budget_usd: float = 50
    default_project_budget_usd: float = 20
    default_task_budget_usd: float = 0.5
    default_max_output_tokens: int = 2048

    # Tier rules use blended price per million tokens (input + output) / 2.
    economy_max_blended_usd: float = 1.0
    standard_max_blended_usd: float = 8.0

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
