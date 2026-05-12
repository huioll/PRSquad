"""Application configuration via environment variables / .env file."""
from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    All settings have safe defaults so the service starts in *demo mode* without secrets.
    Override anything via env (PRSQUAD_GITHUB_TOKEN, etc.) or a .env file.
    """

    model_config = SettingsConfigDict(env_prefix="PRSQUAD_", env_file=".env", extra="ignore")

    # LLM
    llm_provider: Literal["stub", "openai"] = "stub"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0

    # GitHub
    github_token: str | None = None
    github_api_base: str = "https://api.github.com"
    post_comments: bool = False  # default off so we don't spam PRs from local dev

    # Webhook
    webhook_secret: str | None = None

    # Server
    host: str = "0.0.0.0"
    port: int = 8001


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
