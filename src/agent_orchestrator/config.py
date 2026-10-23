"""Runtime configuration via ``pydantic-settings``.

All settings are read from environment variables prefixed with ``ORCH_``
(for example ``ORCH_PORT=8020``), optionally from a local ``.env`` file.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable through ``ORCH_`` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="ORCH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_path: str = "orchestrator.db"
    host: str = "0.0.0.0"
    port: int = 8020
    default_max_attempts: int = 3
    base_delay: float = 0.1
    max_delay: float = 5.0
    jitter: float = 0.0
    log_level: str = "INFO"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached :class:`Settings` instance."""

    return Settings()
