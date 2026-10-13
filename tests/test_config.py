"""Config validation tests (offline, no network/DB)."""
import pytest

from brainrush.config import Settings
from brainrush.healthcheck import validate_config_only


def test_valid_placeholders_pass_validation():
    report = validate_config_only(
        {
            "BOT_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            "DATABASE_URL": "postgresql+asyncpg://user:password@localhost:5432/brainrush",
        }
    )
    assert report.config_ok


def test_empty_token_rejected():
    report = validate_config_only(
        {
            "BOT_TOKEN": "",
            "DATABASE_URL": "postgresql+asyncpg://user:password@localhost:5432/brainrush",
        }
    )
    assert not report.config_ok
    assert "BOT_TOKEN" in (report.config_error or "")


def test_wrong_db_scheme_rejected():
    report = validate_config_only(
        {"BOT_TOKEN": "dummy-token", "DATABASE_URL": "sqlite+aiosqlite:///:memory:"}
    )
    assert not report.config_ok
    assert "postgresql+asyncpg" in (report.config_error or "")


def test_settings_requires_both_fields():
    with pytest.raises(Exception):
        Settings(BOT_TOKEN="", DATABASE_URL="")
