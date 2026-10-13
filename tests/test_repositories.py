"""Repository tests: fake session + statement-shape checks, no real DB.

Conventions follow the existing suite (asyncio_mode=auto, plain async test
functions, offline-safe). No Telegram involvement.
"""
import uuid
from datetime import date

import pytest
from sqlalchemy.dialects import postgresql

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.models import DailyActivity, GameSession, PlayerProfile, User
from brainrush.db.repository import (
    DailyActivityRepository,
    GameResultRepository,
    GameSessionRepository,
    PlayerProfileRepository,
    UserRepository,
)


class FakeResult:
    def __init__(self, rows=(), rowcount=0):
        self._rows = list(rows)
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeTx:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.begun += 1
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.session.tx_committed += 1
        else:
            self.session.rollbacks += 1
        return False


class RecordingSession:
    """Minimal AsyncSession double: serves canned results, records everything."""

    def __init__(self, script=()):
        self._script = list(script)
        self.statements = []
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.begun = 0
        self.tx_committed = 0

    async def execute(self, stmt, *args, **kwargs):
        self.statements.append(stmt)
        assert self._script, "unexpected execute() call"
        return self._script.pop(0)

    async def get(self, model, pk):
        assert self._script, "unexpected get() call"
        return self._script.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    def begin(self):
        return _FakeTx(self)


def _sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _user(**kw):
    kw.setdefault("telegram_id", 123456)
    return User(**kw)


async def test_user_get_or_create_existing_updates_names():
    user = _user(username="old", display_name="Old")
    session = RecordingSession(script=[FakeResult(rows=[user])])
    repo = UserRepository(session)

    found, created = await repo.get_or_create(
        telegram_id=123456, username="new", display_name="New"
    )

    assert found is user and created is False
    assert user.username == "new" and user.display_name == "New"
    assert session.commits == 0 and session.begun == 0


async def test_user_get_or_create_new_uses_on_conflict():
    fresh = _user(username="n")
    session = RecordingSession(
        script=[FakeResult(rows=[]), FakeResult(rowcount=1), FakeResult(rows=[fresh])]
    )
    repo = UserRepository(session)

    found, created = await repo.get_or_create(telegram_id=777, username="n")

    assert found is fresh and created is True
    assert session.commits == 0
    assert any("ON CONFLICT" in _sql(s) for s in session.statements)


@pytest.mark.parametrize("bad", [0, True, "123", None, 1.5])
async def test_user_rejects_bad_telegram_id(bad):
    repo = UserRepository(RecordingSession())
    with pytest.raises(ValueError):
        await repo.get_or_create(telegram_id=bad)


async def test_user_rejects_long_username():
    repo = UserRepository(RecordingSession())
    with pytest.raises(ValueError):
        await repo.get_or_create(telegram_id=1, username="x" * 33)


async def test_profile_record_game_is_single_atomic_update():
    profile = PlayerProfile(user_id=uuid.uuid4())
    session = RecordingSession(
        script=[FakeResult(rowcount=1), FakeResult(rows=[profile])]
    )
    repo = PlayerProfileRepository(session)

    out = await repo.record_game(
        user_id=profile.user_id, xp_earned=10, won=True, new_level=3
    )

    assert out is profile
    assert session.commits == 0
    update_sql = _sql(session.statements[0])
    assert "total_xp +" in update_sql or "total_xp+" in update_sql
    assert "games_played +" in update_sql or "games_played+" in update_sql
    assert "current_level" in update_sql


async def test_profile_record_draw_touches_no_streak():
    profile = PlayerProfile(user_id=uuid.uuid4())
    session = RecordingSession(
        script=[FakeResult(rowcount=1), FakeResult(rows=[profile])]
    )
    repo = PlayerProfileRepository(session)

    await repo.record_game(user_id=profile.user_id, xp_earned=0, won=None)

    update_sql = _sql(session.statements[0])
    assert "current_streak" not in update_sql
    assert "wins" not in update_sql and "losses" not in update_sql


async def test_profile_record_game_missing_profile():
    session = RecordingSession(script=[FakeResult(rowcount=0)])
    repo = PlayerProfileRepository(session)
    with pytest.raises(NotFoundError):
        await repo.record_game(user_id=uuid.uuid4(), xp_earned=5, won=False)
    assert session.commits == 0


async def test_session_finish_requires_started_row():
    missing_session = RecordingSession(script=[None])
    repo = GameSessionRepository(missing_session)
    with pytest.raises(NotFoundError):
        await repo.finish(
            session_id=uuid.uuid4(),
            status="completed",
            score=1,
            ended_at=None,
            duration_seconds=None,
        )

    done = GameSession(user_id=uuid.uuid4(), game_type="quiz", status="completed")
    finished_session = RecordingSession(script=[done])
    repo2 = GameSessionRepository(finished_session)
    with pytest.raises(ConflictError):
        await repo2.finish(
            session_id=uuid.uuid4(),
            status="completed",
            score=1,
            ended_at=None,
            duration_seconds=None,
        )


async def test_session_rejects_bad_status_and_limit():
    repo = GameSessionRepository(RecordingSession())
    with pytest.raises(ValueError):
        await repo.finish(
            session_id=uuid.uuid4(),
            status="bogus",
            score=0,
            ended_at=None,
            duration_seconds=None,
        )
    with pytest.raises(ValueError):
        await repo.list_by_user(user_id=uuid.uuid4(), limit=0)
    with pytest.raises(ValueError):
        await repo.list_by_user(user_id=uuid.uuid4(), status="bogus")


async def test_result_validation():
    repo = GameResultRepository(RecordingSession())
    with pytest.raises(ValueError):
        await repo.record(
            session_id=uuid.uuid4(), score=0, outcome="maybe", xp_earned=0
        )
    with pytest.raises(ValueError):
        await repo.record(
            session_id=uuid.uuid4(), score=-1, outcome="win", xp_earned=0
        )
    with pytest.raises(ValueError):
        await repo.record(
            session_id=uuid.uuid4(), score=0, outcome="win", xp_earned=0,
            metadata="not-a-dict",
        )


async def test_daily_add_play_upserts_then_bumps_atomically():
    from datetime import date as _date

    day = _date(2026, 10, 12)
    row = DailyActivity(user_id=uuid.uuid4(), activity_date=day)
    session = RecordingSession(
        script=[
            FakeResult(rows=[]),  # get_or_create: initial get
            FakeResult(rowcount=1),  # upsert insert
            FakeResult(rows=[row]),  # get_or_create: re-select
            FakeResult(rowcount=1),  # counter bump
            FakeResult(rows=[row]),  # final select
        ]
    )
    repo = DailyActivityRepository(session)

    out = await repo.add_play(user_id=row.user_id, day=day, xp_earned=7)

    assert out is row
    assert session.commits == 0
    compiled = [_sql(s) for s in session.statements]
    assert any("uq_daily_activities_user_date" in s for s in compiled)
    assert any("games_played +" in s or "games_played+" in s for s in compiled)
