"""Tests for environment-driven configuration."""

from __future__ import annotations

from agent_orchestrator.config import Settings, get_settings


def test_defaults():
    settings = Settings()
    assert settings.port == 8020
    assert settings.host == "0.0.0.0"
    assert settings.default_max_attempts == 3
    assert settings.db_path == "orchestrator.db"


def test_env_prefix_override(monkeypatch):
    monkeypatch.setenv("ORCH_PORT", "9000")
    monkeypatch.setenv("ORCH_DB_PATH", "/tmp/custom.db")
    settings = Settings()
    assert settings.port == 9000
    assert settings.db_path == "/tmp/custom.db"


def test_get_settings_is_cached(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("ORCH_MAX_DELAY", "42")
    assert get_settings().max_delay == 42.0
    assert get_settings() is get_settings()
    get_settings.cache_clear()
