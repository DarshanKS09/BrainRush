"""Service tests: stub repositories + fake session, no real DB or Telegram.

Verifies transaction ownership (one `begin()` per call, zero direct commits),
input validation, missing-record mapping, and the UTC date policy.
"""
import uuid
from datetime import datetime, timezone

import pytest

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.models import DailyActivity, GameResult, GameSession, PlayerProfile, User
from brainrush.services import utc_today
from brainrush.services.games import GameSessionService
from brainrush.services.profiles import ProfileService
from brainrush.services.users import UserService
from tests.test_repositories import RecordingSession


def _aware(year=2026, month=10, day=12, hour=10):
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


class StubUsers:
    def __init__(self):
        self.by_tid = {}
        self.by_id = {}

    async def get_by_id(self, uid):
        return self.by_id.get(uid)

    async def get_or_create(self, *, telegram_id, username=None, display_name=None):
        if telegram_id in self.by_tid:
            user = self.by_tid[telegram_id]
            if username is not None:
                user.username = username
            if display_name is not None:
                user.display_name = display_name
            return user, False
        user = User(telegram_id=telegram_id, username=username, display_name=display_name)
        user.id = uuid.uuid4()
        self.by_tid[telegram_id] = user
        self.by_id[user.id] = user
        return user, True


class StubProfiles:
    def __init__(self):
        self.by_user = {}
        self.calls = []

    async def get_by_user_id(self, uid):
        return self.by_user.get(uid)

    async def get_or_create(self, *, user_id):
        if user_id in self.by_user:
            return self.by_user[user_id], False
        profile = PlayerProfile(
            user_id=user_id, total_xp=0, current_level=1, games_played=0,
            wins=0, losses=0, current_streak=0, longest_streak=0,
        )
        profile.id = uuid.uuid4()
        self.by_user[user_id] = profile
        return profile, True

    async def add_xp(self, *, user_id, amount):
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            raise ValueError("amount must be an int >= 0")
        profile = self.by_user.get(user_id)
        if profile is None:
            raise NotFoundError("player profile not found")
        profile.total_xp += amount
        self.calls.append(("add_xp", user_id, amount))
        return profile

    async def record_game(self, *, user_id, xp_earned, won, new_level=None):
        profile = self.by_user.get(user_id)
        if profile is None:
            raise NotFoundError("player profile not found")
        profile.total_xp += xp_earned
        profile.games_played += 1
        if won is True:
            profile.wins += 1
            profile.current_streak += 1
            profile.longest_streak = max(profile.longest_streak, profile.current_streak)
        elif won is False:
            profile.losses += 1
            profile.current_streak = 0
        if new_level is not None:
            profile.current_level = new_level
        self.calls.append(("record_game", user_id, xp_earned, won, new_level))
        return profile


class StubSessions:
    def __init__(self):
        self.rows = {}
        self.calls = []

    async def get_by_id(self, sid):
        return self.rows.get(sid)

    async def create(self, *, user_id, game_type):
        if not game_type or not game_type.strip() or len(game_type) > 64:
            raise ValueError("bad game_type")
        row = GameSession(user_id=user_id, game_type=game_type, status="started")
        row.id = uuid.uuid4()
        row.started_at = _aware()
        self.rows[row.id] = row
        self.calls.append(("create", user_id, game_type))
        return row

    async def finish(self, *, session_id, status, score, ended_at, duration_seconds):
        row = self.rows.get(session_id)
        if row is None:
            raise NotFoundError("game session not found")
        if row.status != "started":
            raise ConflictError(f"session is already {row.status}")
        row.status = status
        row.score = score
        row.ended_at = ended_at
        row.duration_seconds = duration_seconds
        self.calls.append(("finish", session_id, status, score))
        return row

    async def abandon(self, *, session_id, ended_at):
        return await self.finish(
            session_id=session_id, status="abandoned", score=0,
            ended_at=ended_at, duration_seconds=None,
        )


class StubResults:
    def __init__(self):
        self.by_session = {}
        self.calls = []

    async def get_by_session(self, sid):
        return self.by_session.get(sid)

    async def record(self, *, session_id, score, outcome, xp_earned, metadata=None):
        if outcome not in ("win", "loss", "draw"):
            raise ValueError("bad outcome")
        row = GameResult(
            session_id=session_id, score=score, outcome=outcome,
            xp_earned=xp_earned, result_metadata=dict(metadata) if metadata else {},
        )
        row.id = uuid.uuid4()
        self.by_session[session_id] = row
        self.calls.append(("record", session_id, outcome, score, xp_earned))
        return row


class StubActivities:
    def __init__(self):
        self.rows = {}
        self.calls = []

    async def add_play(self, *, user_id, day, xp_earned):
        key = (user_id, day)
        row = self.rows.get(key)
        if row is None:
            row = DailyActivity(
                user_id=user_id, activity_date=day, games_played=0, xp_earned=0
            )
            row.id = uuid.uuid4()
            self.rows[key] = row
        row.games_played += 1
        row.xp_earned += xp_earned
        self.calls.append(("add_play", user_id, day, xp_earned))
        return row


def _user_service(session, users=None, profiles=None):
    svc = UserService(session)
    svc.users = users or StubUsers()
    svc.profiles = profiles or StubProfiles()
    return svc


def _game_service(session, users=None, sessions=None, results=None, profiles=None, activities=None):
    svc = GameSessionService(session)
    svc.users = users or StubUsers()
    svc.sessions = sessions or StubSessions()
    svc.results = results or StubResults()
    svc.profiles = profiles or StubProfiles()
    svc.activities = activities or StubActivities()
    return svc


async def test_get_or_register_creates_user_and_profile_once():
    session = RecordingSession()
    users, profiles = StubUsers(), StubProfiles()
    svc = _user_service(session, users, profiles)

    user, profile = await svc.get_or_register(
        telegram_id=42, username="Ada", display_name="Ada L"
    )
    again, profile2 = await svc.get_or_register(telegram_id=42)

    assert again.id == user.id and profile2 is profile
    assert len(users.by_tid) == 1
    assert session.begun == 2 and session.commits == 0


async def test_start_session_missing_user():
    session = RecordingSession()
    svc = _game_service(session)
    with pytest.raises(NotFoundError):
        await svc.start_session(user_id=uuid.uuid4(), game_type="quiz")


async def test_finish_happy_path_single_transaction_utc_day():
    session = RecordingSession()
    users, sessions = StubUsers(), StubSessions()
    svc = _game_service(session, users=users, sessions=sessions)
    # register through the same stubs
    reg = _user_service(session, users, svc.profiles)
    user, _ = await reg.get_or_register(telegram_id=7)
    begun_before = session.begun

    played_at = _aware(hour=23)
    started = await svc.start_session(user_id=user.id, game_type="quiz")
    sess, result, profile, activity = await svc.finish_session(
        session_id=started.id, outcome="win", score=90, xp_earned=25,
        metadata={"q": 10}, new_level=2, played_at=played_at,
    )

    assert sess.status == "completed"
    assert result.outcome == "win" and result.score == 90
    assert result.result_metadata == {"q": 10}
    assert profile.wins == 1 and profile.total_xp == 25
    assert profile.current_streak == 1 and profile.current_level == 2
    assert activity.activity_date == played_at.date()
    assert activity.games_played == 1 and activity.xp_earned == 25
    assert sess.duration_seconds is not None and sess.duration_seconds >= 0
    # finish itself owns exactly one transaction; no direct commits anywhere
    assert session.begun == begun_before + 2 and session.commits == 0


async def test_finish_defaults_to_utc_today():
    session = RecordingSession()
    users = StubUsers()
    svc = _game_service(session, users=users)
    reg = _user_service(session, users, svc.profiles)
    user, _ = await reg.get_or_register(telegram_id=9)
    started = await svc.start_session(user_id=user.id, game_type="memory")

    _, _, _, activity = await svc.finish_session(
        session_id=started.id, outcome="draw", score=5, xp_earned=2
    )

    assert activity.activity_date == utc_today()
    assert svc.profiles.by_user[user.id].wins == 0
    assert svc.profiles.by_user[user.id].losses == 0


async def test_finish_missing_and_double_finish():
    session = RecordingSession()
    svc = _game_service(session)
    with pytest.raises(NotFoundError):
        await svc.finish_session(
            session_id=uuid.uuid4(), outcome="win", score=1, xp_earned=1
        )

    users = StubUsers()
    svc2 = _game_service(session, users=users)
    reg = _user_service(session, users, svc2.profiles)
    user, _ = await reg.get_or_register(telegram_id=11)
    started = await svc2.start_session(user_id=user.id, game_type="quiz")
    await svc2.finish_session(
        session_id=started.id, outcome="loss", score=1, xp_earned=0
    )
    assert svc2.profiles.by_user[user.id].current_streak == 0
    with pytest.raises(ConflictError):
        await svc2.finish_session(
            session_id=started.id, outcome="win", score=9, xp_earned=9
        )


async def test_finish_validates_outcome_and_naive_datetime():
    session = RecordingSession()
    svc = _game_service(session)
    with pytest.raises(ValueError):
        await svc.finish_session(
            session_id=uuid.uuid4(), outcome="maybe", score=0, xp_earned=0
        )
    with pytest.raises(ValueError):
        await svc.finish_session(
            session_id=uuid.uuid4(), outcome="win", score=0, xp_earned=0,
            played_at=datetime(2026, 10, 12, 10, 0, 0),
        )


async def test_abandon_records_nothing_else():
    session = RecordingSession()
    users = StubUsers()
    svc = _game_service(session, users=users)
    reg = _user_service(session, users, svc.profiles)
    user, _ = await reg.get_or_register(telegram_id=13)
    started = await svc.start_session(user_id=user.id, game_type="quiz")

    out = await svc.abandon_session(session_id=started.id)

    assert out.status == "abandoned"
    assert svc.results.calls == [] and svc.activities.calls == []
    assert svc.profiles.calls == []


async def test_profile_service_errors_and_rollback():
    session = RecordingSession()
    profiles = StubProfiles()
    svc = ProfileService(session)
    svc.profiles = profiles

    with pytest.raises(NotFoundError):
        await svc.get_stats(user_id=uuid.uuid4())
    with pytest.raises(ValueError):
        await svc.record_game(user_id=uuid.uuid4(), outcome="nope", xp_earned=1)
    with pytest.raises(ValueError):
        await svc.add_xp(user_id=uuid.uuid4(), amount=-5)
    assert session.commits == 0
