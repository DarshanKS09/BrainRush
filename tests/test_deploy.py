"""Deployment validation: provider PORT override + deploy-file static checks.

Offline, no network/DB. Secrets are never asserted on (only key presence and
safe defaults).
"""
from pathlib import Path

import pytest

from brainrush.config import Settings, api_listen

ROOT = Path(__file__).resolve().parent.parent


def _settings(**overrides):
    base = dict(
        BOT_TOKEN="dummy-token",
        DATABASE_URL="postgresql+asyncpg://user:password@localhost:5432/brainrush",
    )
    base.update(overrides)
    return Settings(**base)


def test_api_listen_defaults():
    assert api_listen(_settings()) == ("127.0.0.1", 8000)


def test_provider_port_overrides_api_port():
    assert api_listen(_settings(PORT=10000, API_PORT=8000)) == ("127.0.0.1", 10000)
    assert api_listen(_settings(API_HOST="0.0.0.0", PORT=443)) == ("0.0.0.0", 443)


def test_invalid_port_rejected():
    with pytest.raises(Exception):
        _settings(PORT=0)
    with pytest.raises(Exception):
        _settings(API_PORT=99999)


def test_production_auth_defaults_are_locked_down():
    settings = _settings()
    assert settings.ALLOW_DEV_AUTH is False
    assert settings.DEV_AUTH_TELEGRAM_ID == 0


def test_dockerfile_serves_combined_process_without_automigrate():
    text = (ROOT / "Dockerfile").read_text()
    assert "python" in text and "--serve-api" in text
    run_lines = [ln for ln in text.splitlines() if ln.strip().startswith("RUN")]
    assert run_lines, "Dockerfile must have RUN steps"
    assert not any("alembic" in ln for ln in run_lines)


def test_fly_single_machine_with_health_check():
    text = (ROOT / "fly.toml").read_text()
    assert "/health" in text
    assert "auto_stop_machines = false" in text
    assert "min_machines_running = 1" in text


def test_render_single_instance_with_health_check():
    text = (ROOT / "render.yaml").read_text()
    assert "numInstances: 1" in text
    assert "healthCheckPath: /health" in text


def test_ci_runs_backend_and_frontend():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "pytest" in text
    assert "npm run build" in text


def test_env_example_documents_prod_vars_without_secrets():
    text = (ROOT / ".env.example").read_text()
    for key in (
        "BOT_TOKEN",
        "DATABASE_URL",
        "WEBAPP_URL",
        "API_HOST",
        "API_PORT",
        "API_CORS_ORIGINS",
    ):
        assert key in text
    # No real-looking token or password material may live in the example.
    assert "AAE" not in text and "supabase.co" not in text
