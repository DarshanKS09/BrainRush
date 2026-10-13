"""Offline schema tests: inspect metadata only, no DB connection."""
from sqlalchemy import UUID
from sqlalchemy.dialects.postgresql import JSONB

from brainrush.db.base import Base
import brainrush.db.models  # noqa: F401  (register tables)


def _table(name: str):
    assert name in Base.metadata.tables, f"missing table {name}"
    return Base.metadata.tables[name]


def test_all_tables_present():
    for name in (
        "users",
        "player_profiles",
        "game_sessions",
        "game_results",
        "daily_activities",
    ):
        _table(name)


def test_uuid_primary_keys():
    for name in (
        "users",
        "player_profiles",
        "game_sessions",
        "game_results",
        "daily_activities",
    ):
        pk_cols = [c for c in _table(name).columns if c.primary_key]
        assert len(pk_cols) == 1, name
        assert isinstance(pk_cols[0].type, UUID), name


def test_users_telegram_id_unique_bigint():
    col = _table("users").columns["telegram_id"]
    assert col.unique
    assert col.index
    assert col.nullable is False
    assert col.type.__class__.__name__ in ("BIGINT", "BigInteger")


def test_profile_one_to_one_with_user():
    table = _table("player_profiles")
    assert table.columns["user_id"].nullable is False
    fk_targets = {fk.target_fullname for fk in table.columns["user_id"].foreign_keys}
    assert "users.id" in fk_targets
    uq_cols = [
        sorted(c.columns.keys())
        for c in table.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert ["user_id"] in uq_cols


def test_session_foreign_key_and_status_check():
    table = _table("game_sessions")
    fk_targets = {fk.target_fullname for fk in table.columns["user_id"].foreign_keys}
    assert "users.id" in fk_targets
    checks = " ".join(str(c.sqltext) for c in table.constraints if c.__class__.__name__ == "CheckConstraint")
    assert "status" in checks


def test_result_jsonb_and_unique_session():
    table = _table("game_results")
    assert isinstance(table.columns["metadata"].type, JSONB)
    uq_cols = [
        sorted(c.columns.keys())
        for c in table.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert ["session_id"] in uq_cols
    fk_targets = {fk.target_fullname for fk in table.columns["session_id"].foreign_keys}
    assert "game_sessions.id" in fk_targets
    checks = " ".join(str(c.sqltext) for c in table.constraints if c.__class__.__name__ == "CheckConstraint")
    assert "outcome" in checks


def test_daily_activity_unique_user_date():
    table = _table("daily_activities")
    uq_cols = [
        sorted(c.columns.keys())
        for c in table.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert ["activity_date", "user_id"] in uq_cols
    assert table.columns["activity_date"].nullable is False


def test_timezone_aware_timestamps():
    for name, colname in [
        ("users", "created_at"),
        ("users", "updated_at"),
        ("player_profiles", "created_at"),
        ("game_sessions", "started_at"),
        ("game_results", "created_at"),
        ("daily_activities", "activity_date"),
    ]:
        col = _table(name).columns[colname]
        if colname == "activity_date":
            assert col.type.__class__.__name__ == "Date"
        else:
            assert getattr(col.type, "timezone", False) is True, f"{name}.{colname}"
