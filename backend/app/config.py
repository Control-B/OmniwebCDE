from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="OMNIWEB_", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./omniweb.db"
    frontend_origin: str = "http://localhost:43210"
    oidc_issuer: str = ""
    oidc_audience: str = "omniweb-api"
    oidc_discovery_url: str = ""
    encryption_key: str = ""
    model_gateway_url: str = "http://127.0.0.1:8020"
    model_gateway_secret: str = Field(default="", repr=False)
    digitalocean_base_url: str = "https://api.digitalocean.com/v2"
    coder_base_url: str = "http://coder:7080"
    coder_access_url: str = "http://coder.localhost"
    coder_token: str = Field(default="", repr=False)
    mock_infrastructure: bool = True

    # Application builder. Generated code runs only inside the sandbox selected here.
    builder_data_dir: str = "./.omniweb"
    builder_toolchain_dir: str = ""
    sandbox_mode: Literal["namespace", "container", "disabled"] = "namespace"
    sandbox_image: str = "ghcr.io/omniweb/generated-app-runner:2026.10"
    sandbox_timeout_seconds: int = 300
    preview_url: str = "http://localhost:43230"
    # Each project's preview gets its own origin (<token>.preview.<host>) so generated apps cannot
    # read each other's storage. Browsers resolve *.localhost to loopback, so this works locally.
    preview_subdomains: bool = True
    max_repair_attempts: int = 2

    # GitHub App used for repository sync. Without an app ID, a local mock remote is used.
    github_app_id: str = ""
    github_app_private_key: str = Field(default="", repr=False)
    github_api_url: str = "https://api.github.com"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def allowed_frontend_origins(self) -> list[str]:
        origins = {self.frontend_origin.rstrip("/")}
        if not self.is_production:
            if "localhost" in self.frontend_origin:
                origins.add(self.frontend_origin.replace("localhost", "127.0.0.1").rstrip("/"))
            if "127.0.0.1" in self.frontend_origin:
                origins.add(self.frontend_origin.replace("127.0.0.1", "localhost").rstrip("/"))
        return sorted(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()
