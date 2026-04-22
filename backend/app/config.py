"""Application configuration loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    cors_allowed_origins: str = "http://localhost:5173"

    database_url: str = Field(
        default="postgresql+asyncpg://rmt_dev:CHANGE_ME@localhost:5432/rmt_dev",
        description="Async SQLAlchemy URL (postgresql+asyncpg://…).",
    )

    godaddy_api_key: SecretStr = SecretStr("")
    godaddy_api_secret: SecretStr = SecretStr("")
    godaddy_api_base: str = "https://api.godaddy.com"

    combell_api_key: SecretStr = SecretStr("")
    combell_api_secret: SecretStr = SecretStr("")
    combell_api_base: str = "https://api.combell.com"

    public_fqdn: str = "localhost"
    letsencrypt_email: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def sync_database_url(self) -> str:
        """Alembic uses the sync driver for migrations — strip the +asyncpg suffix."""
        return self.database_url.replace("+asyncpg", "")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
