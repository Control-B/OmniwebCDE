from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="OMNIWEB_", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./omniweb.db"
    frontend_origin: str = "http://localhost:43210"
    oidc_issuer: str = ""
    oidc_audience: str = "omniweb-api"
    encryption_key: str = ""
    digitalocean_base_url: str = "https://api.digitalocean.com/v2"
    coder_base_url: str = "http://coder:7080"
    coder_access_url: str = "http://coder.localhost"
    coder_token: str = Field(default="", repr=False)
    mock_infrastructure: bool = True

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
