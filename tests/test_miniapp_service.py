"""Mini App service flows with scripted sessions. No real DB, no Telegram."""
import uuid
from datetime import date

import pytest

from brainrush.db.errors import NotFoundError
from brainrush.db.models import DailyActivity, GameSession, PlayerProfile, User, WebappGameState
from brainrush.services.miniapp import MiniappGameService
from tests.test_repositories import FakeResult, RecordingSession


def _user():
    user = User(telegram_id=9001, username="webb", display_name="Web B")
    user.id = uuid.uuid4()
    return user


def _profile(user_id, total_xp=0):
    profile = PlayerProfile(
        user_id=user_id, total_xp=total_xp, current_level=1, games_played=0,
        wins=0, losses=0, current_streak=0, longest_streak=0,
    )
    profile.id = uuid.uuid4()
    return profile


def _state(user_id, session_id, secret=42, max_attempts=7, guesses=None):
    row = WebappGameState(
        user_id=user_id, session_id=session_id, game_type="number_guessing",
        difficulty="hard", secret=secret, max_attempts=max_attempts,
        guesses=list(guesses or []),
    )
    row.id = uuid.uuid4()
    return row


def _session_row(user_id, status="started"):
    row = GameSession(user_id=user_id, game_type="number_guessing", status=status)
    row.id = uuid.uuid4()
    return row


def _no_secret_leak(obj) -> bool:
    if isinstance(obj, dict):
        if "secret" in obj:
            return False
        return all(_no_secret_leak(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_no_secret_leak(v) for v in obj)
    return True


async def test_start_abandons_stale_then_creates_public_view(monkeypatch):
    user = _user()
    stale_state = _state(user.id, uuid.uuid4())
    stale_done = _session_row(user.id, status="abandoned")
    monkeypatch.setattr(
        "brainrush.services.miniapp.guessing.roll_secret", lambda config: 42
    )
    session = RecordingSession(
        script=[
            user,  # start: user check (get)
            FakeResult(rows=[(stale_state, _session_row(user.id))]),  # sweep list
            _session_row(user.id),  # abandon: get started row
            FakeResult(rowcount=1),  # abandon: update
            stale_done,  # abandon: re-get
            # session.create + state.create use add/flush only
        ]
    )
    svc = MiniappGameService(session)
    view = await svc.start_game(user_id=user.id, difficulty="hard")

    assert view["finished"] is False and view["attempts_left"] == 7
    assert view["difficulty"] == "hard" and view["max_attempts"] == 7
    assert _no_secret_leak(view)
    assert session.commits == 0


async def test_start_rejects_bad_difficulty():
    svc = MiniappGameService(RecordingSession())
    with pytest.raises(ValueError):
        await svc.start_game(user_id=uuid.uuid4(), difficulty="extreme")


async def test_guess_hint_then_idempotent_retry():
    user = _user()
    sid = uuid.uuid4()
    state = _state(user.id, sid, secret=42)
    session = RecordingSession(script=[FakeResult(rows=[state])])
    svc = MiniappGameService(session)

    first = await svc.guess(
        session_id=sid, user_id=user.id, value=50, client_guess_id="c1"
    )
    assert first["guesses"] == [{"value": 50, "hint": "high"}]
    assert first["attempts_left"] == 6
    assert _no_secret_leak(first)

    # retry with a *different* id consumes a second attempt
    state2 = _state(user.id, sid, secret=42,
                    guesses=[{"id": "c1", "value": 50}])
    session2 = RecordingSession(script=[FakeResult(rows=[state2])])
    svc2 = MiniappGameService(session2)
    second = await svc2.guess(
        session_id=sid, user_id=user.id, value=30, client_guess_id="c2"
    )
    assert [g["value"] for g in second["guesses"]] == [50, 30]


async def test_guess_same_id_does_not_consume():
    user = _user()
    sid = uuid.uuid4()
    state = _state(user.id, sid, secret=42,
                   guesses=[{"id": "c1", "value": 50}])
    session = RecordingSession(script=[FakeResult(rows=[state])])
    svc = MiniappGameService(session)

    view = await svc.guess(
        session_id=sid, user_id=user.id, value=50, client_guess_id="c1"
    )
    assert view["attempts_used"] == 1 and view["attempts_left"] == 6


async def test_winning_guess_completes_and_reveals(monkeypatch):
    monkeypatch.setattr(
        "brainrush.services.miniapp.guessing.roll_secret", lambda config: 42
    )
    user = _user()
    sid = uuid.uuid4()
    prior = [{"id": "c1", "value": 50}, {"id": "c2", "value": 30}]
    state = _state(user.id, sid, secret=42, guesses=prior)
    started = _session_row(user.id)
    done = _session_row(user.id, status="completed")
    profile = _profile(user.id, total_xp=50)  # 0 + 50 XP for 3-attempt win
    activity = DailyActivity(user_id=user.id, activity_date=date(2026, 1, 1),
                             games_played=1, xp_earned=50)
    session = RecordingSession(
        script=[
            FakeResult(rows=[state]),  # guess: locked state
            started,  # finish: get session
            FakeResult(rowcount=1),  # finish: update session
            done,  # finish: re-get
            # results.record: add/flush
            FakeResult(rowcount=1),  # profiles.record_game: update
            FakeResult(rows=[profile]),  # profiles.record_game: re-select
            FakeResult(rowcount=1),  # profiles.set_level: update
            FakeResult(rows=[profile]),  # profiles.set_level: re-select
            FakeResult(rows=[]),  # activities: get (absent)
            FakeResult(rowcount=1),  # activities: upsert
            FakeResult(rows=[activity]),  # activities: re-select
            FakeResult(rowcount=1),  # activities: bump
            FakeResult(rows=[activity]),  # activities: final select
            # states.delete
        ]
    )
    svc = MiniappGameService(session)
    view = await svc.guess(
        session_id=sid, user_id=user.id, value=42, client_guess_id="c3"
    )

    assert view["finished"] is True
    assert view["result"] == {"outcome": "win", "score": 3,
                              "xp_earned": 50, "secret": 42}
    assert [g["value"] for g in view["guesses"]] == [50, 30, 42]
    assert session.deleted == [state]
    assert session.commits == 0


async def test_wrong_owner_gets_404_without_leak():
    owner = uuid.uuid4()
    intruder = uuid.uuid4()
    sid = uuid.uuid4()
    state = _state(owner, sid)
    foreign_session = _session_row(owner)
    session = RecordingSession(
        script=[FakeResult(rows=[state]), foreign_session]
    )
    svc = MiniappGameService(session)
    with pytest.raises(NotFoundError):
        await svc.guess(
            session_id=sid, user_id=intruder, value=10, client_guess_id="x"
        )


async def test_cancel_is_idempotent_and_xpless():
    user = _user()
    sid = uuid.uuid4()
    state = _state(user.id, sid)
    started = _session_row(user.id)
    done = _session_row(user.id, status="abandoned")
    session = RecordingSession(
        script=[
            FakeResult(rows=[state]),  # cancel 1: locked state
            started,  # abandon: get
            FakeResult(rowcount=1),  # abandon: update
            done,  # abandon: re-get
            # states.delete
            FakeResult(rows=[]),  # cancel 2: state gone
            done,  # cancel 2: session row (abandoned, owned)
        ]
    )
    svc = MiniappGameService(session)
    first = await svc.cancel(session_id=sid, user_id=user.id)
    second = await svc.cancel(session_id=sid, user_id=user.id)
    assert first["status"] == "abandoned"
    assert second["status"] == "abandoned"
    assert len(session.deleted) == 1


async def test_dashboard_shape_uses_real_numbers():
    user = _user()
    profile = _profile(user.id, total_xp=150)
    session = RecordingSession(
        script=[
            user,  # users.get_by_id
            FakeResult(rows=[profile]),  # profiles.get_by_user_id
            FakeResult(rows=[]),  # activities.get (none today)
            FakeResult(rows=[3]),  # best_win_score
            FakeResult(rows=[2]),  # rank count -> rank 3
            FakeResult(rows=[]),  # active states
        ]
    )
    svc = MiniappGameService(session)
    dash = await svc.dashboard(user_id=user.id)

    assert dash["user"]["telegram_id"] == 9001
    assert dash["profile"]["level"] == 2
    assert dash["profile"]["total_xp"] == 150
    assert dash["profile"]["xp_into_level"] == 50
    assert dash["today"] == {"games_played": 0, "xp_earned": 0}
    assert dash["best_win_attempts"] == 3
    assert dash["rank"] == 3
    assert dash["active_games"] == []
