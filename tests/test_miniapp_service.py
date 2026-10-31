"""Mini App service flows with scripted sessions. No real DB, no Telegram."""
import uuid
from datetime import date

import pytest

from brainrush.db.errors import NotFoundError
from brainrush.db.models import DailyActivity, GameResult, GameSession, PlayerProfile, User, WebappGameState
from brainrush.game.maze_race import MAZE_DIFFICULTIES
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
            FakeResult(rowcount=0),  # expire sweep: nothing stale
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
            FakeResult(rowcount=0),  # expire sweep: nothing stale
            user,  # users.get_by_id
            FakeResult(rows=[profile]),  # profiles.get_by_user_id
            FakeResult(rows=[]),  # activities.get (none today)
            FakeResult(rows=[3]),  # best_win_score (number guessing)
            FakeResult(rows=[]),  # best color level (none yet)
            FakeResult(rows=[]),  # best reflex score (none yet)
            FakeResult(rows=[]),  # best perfect error (none yet)
            FakeResult(rows=[]),  # best maze time (none yet)
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
    assert dash["best_color_level"] is None
    assert dash["best_reflex_score"] is None
    assert dash["best_perfect_error_ms"] is None
    assert dash["best_maze_time_ms"] is None
    assert dash["rank"] == 3
    assert dash["active_games"] == []


async def test_dashboard_expires_stale_and_cleans_orphan_states():
    from sqlalchemy.dialects import postgresql

    user = _user()
    profile = _profile(user.id, total_xp=150)
    session = RecordingSession(
        script=[
            FakeResult(rowcount=2),  # expire sweep: two stale rows
            FakeResult(rowcount=1),  # orphan state cleanup
            user,  # users.get_by_id
            FakeResult(rows=[profile]),  # profiles.get_by_user_id
            FakeResult(rows=[]),  # activities.get (none today)
            FakeResult(rows=[3]),  # best_win_score
            FakeResult(rows=[]),  # best color level
            FakeResult(rows=[]),  # best reflex score
            FakeResult(rows=[]),  # best perfect error
            FakeResult(rows=[]),  # best maze time
            FakeResult(rows=[2]),  # rank count -> rank 3
            FakeResult(rows=[]),  # active states (stale ones gone)
        ]
    )
    svc = MiniappGameService(session)
    dash = await svc.dashboard(user_id=user.id)

    assert dash["rank"] == 3 and dash["active_games"] == []
    assert session.tx_committed == 1 and session.commits == 0
    first = str(
        session.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "expired" in first


async def test_history_expires_stale_before_reading():
    from datetime import datetime, timezone

    user = _user()
    old = _session_row(user.id, status="expired")
    old.started_at = datetime(2026, 10, 1, tzinfo=timezone.utc)
    old.ended_at = datetime(2026, 10, 2, tzinfo=timezone.utc)
    session = RecordingSession(
        script=[
            FakeResult(rowcount=1),  # expire sweep: one stale row
            FakeResult(rowcount=0),  # orphan state cleanup
            FakeResult(rows=[(old, None)]),  # history select
        ]
    )
    svc = MiniappGameService(session)
    items = await svc.history(user_id=user.id)

    assert len(items) == 1
    assert items[0]["status"] == "expired"
    assert items[0]["outcome"] is None and items[0]["xp_earned"] == 0
    assert session.tx_committed == 1 and session.commits == 0


# --- Maze Race regressions -------------------------------------------------
# Production-shaped fixtures: `_start_maze` stores the wall bitmasks as a
# raw int list in `guesses["walls"]` (confirmed against the live DB), and a
# dashboard call must render any active state without raising.


def _maze_state(user_id, session_id, difficulty="medium", player=None, moves=0):
    config = MAZE_DIFFICULTIES[difficulty]
    guesses = {
        "game": "maze_race",
        "difficulty": difficulty,
        "walls": [0] * (config.rows * config.cols),  # all cells open (deterministic)
        "player": dict(player or {"r": 0, "c": 0}),
        "visited": [[False] * config.cols for _ in range(config.rows)],
        "moves": moves,
        "started_at": "2026-10-30T16:07:41+00:00",
        "solution_length": 25,
    }
    guesses["visited"][0][0] = True
    row = WebappGameState(
        user_id=user_id, session_id=session_id, game_type="maze_race",
        difficulty=difficulty, secret=0, max_attempts=config.rows * config.cols,
        guesses=guesses,
    )
    row.id = uuid.uuid4()
    return row


def _maze_session_row(user_id, status="started", session_id=None):
    row = GameSession(user_id=user_id, game_type="maze_race", status=status)
    row.id = session_id or uuid.uuid4()
    return row


def _maze_result_row(session_id, metadata):
    row = GameResult(
        session_id=session_id, score=42000, outcome="win", xp_earned=95,
        result_metadata=metadata,
    )
    row.id = uuid.uuid4()
    return row


def _dashboard_script(user, profile, active_rows):
    return RecordingSession(
        script=[
            FakeResult(rowcount=0),  # expire sweep: nothing stale
            user,  # users.get_by_id
            FakeResult(rows=[profile]),  # profiles.get_by_user_id
            FakeResult(rows=[]),  # activities.get (none today)
            FakeResult(rows=[3]),  # best_win_score (number guessing)
            FakeResult(rows=[]),  # best color level
            FakeResult(rows=[]),  # best reflex score
            FakeResult(rows=[]),  # best perfect error
            FakeResult(rows=[]),  # best maze time
            FakeResult(rows=[0]),  # rank count -> rank 1
            FakeResult(rows=active_rows),  # active states
        ]
    )


async def test_dashboard_renders_active_maze_session():
    """Regression: an active Maze Race state crashed `_active_view` (its
    `guesses` is a dict, not a list) -> unhandled 500 -> the dashboard
    surfaced "Failed to fetch" for as long as the session stayed active."""
    user = _user()
    profile = _profile(user.id, total_xp=150)
    sid = uuid.uuid4()
    maze_state = _maze_state(user.id, sid)
    maze_row = _maze_session_row(user.id, session_id=sid)
    session = _dashboard_script(user, profile, [(maze_state, maze_row)])
    svc = MiniappGameService(session)

    dash = await svc.dashboard(user_id=user.id)

    assert len(dash["active_games"]) == 1
    game = dash["active_games"][0]
    assert game["game_type"] == "maze_race"
    assert game["difficulty"] == "medium"
    assert game["session_id"] == str(sid)
    assert game["finished"] is False and game["status"] == "started"
    assert game["maze"]["rows"] == 13 and game["maze"]["cols"] == 13
    assert game["player"] == {"r": 0, "c": 0}
    assert game["exit"] == {"r": 12, "c": 12}
    assert game["valid_directions"] == ["right", "down"]  # all-open grid
    assert game["moves"] == 0 and game["attempts_used"] == 0
    assert "secret" not in game


async def test_dashboard_renders_other_active_game_types():
    """The new Maze branch must not disturb the other game-type dispatches."""
    user = _user()
    profile = _profile(user.id)
    guess_sid = uuid.uuid4()
    color_sid = uuid.uuid4()
    guess_state = _state(user.id, guess_sid)  # number_guessing, guesses=[]
    color_state = WebappGameState(
        user_id=user.id, session_id=color_sid, game_type="color_sequence",
        difficulty="medium", secret=7, max_attempts=8,
        guesses={"sequence": [1, 2, 3], "position": 0, "level": 3,
                 "levels_completed": 2, "log": []},
    )
    color_state.id = uuid.uuid4()
    guess_row = _session_row(user.id)
    color_row = GameSession(
        user_id=user.id, game_type="color_sequence", status="started"
    )
    color_row.id = color_sid
    session = _dashboard_script(
        user, profile, [(guess_state, guess_row), (color_state, color_row)]
    )
    svc = MiniappGameService(session)

    dash = await svc.dashboard(user_id=user.id)

    by_type = {g["game_type"]: g for g in dash["active_games"]}
    assert set(by_type) == {"number_guessing", "color_sequence"}
    assert by_type["number_guessing"]["attempts_left"] == 7
    assert by_type["color_sequence"]["level"] == 3
    assert by_type["color_sequence"]["display"] == [1, 2, 3]


async def test_completed_maze_session_returns_replay_view():
    """Regression: the state row is deleted on completion, so the replay
    path passed `state=None` into `_maze_public_view` -> AttributeError ->
    unhandled 500 ("Failed to fetch") when re-opening a finished session."""
    user = _user()
    sid = uuid.uuid4()
    done = _maze_session_row(user.id, status="completed", session_id=sid)
    metadata = {
        "game": "maze_race",
        "difficulty": "hard",
        "rows": 17, "cols": 17,
        "elapsed_ms": 42000,
        "moves": 60,
        "solution_length": 48,
        "xp_breakdown": {"base": 100, "time_bonus": 0, "path_bonus": 0,
                         "total": 95},
        "log": [],
    }
    result = _maze_result_row(sid, metadata)
    session = RecordingSession(
        script=[
            FakeResult(rows=[]),  # state gone (deleted on completion)
            done,  # sessions.get_by_id
            FakeResult(rows=[result]),  # results.get_by_session
        ]
    )
    svc = MiniappGameService(session)

    view = await svc.get_state(session_id=sid, user_id=user.id)

    assert view["finished"] is True and view["status"] == "completed"
    assert view["game_type"] == "maze_race"
    assert view["difficulty"] == "hard"
    assert view["session_id"] == str(sid)
    assert view["maze"]["rows"] == 17 and view["maze"]["cols"] == 17
    assert view["max_attempts"] == 17 * 17
    assert view["result"] == {
        "outcome": "win",
        "score": 42000,
        "xp_earned": 95,
        "elapsed_ms": 42000,
        "moves": 60,
        "xp_breakdown": {"base": 100, "time_bonus": 0, "path_bonus": 0,
                         "total": 95},
    }


async def test_completed_maze_replay_tolerates_sparse_metadata():
    """Degraded metadata (no difficulty/rows/cols) must still yield a valid
    finished view instead of KeyError/IndexError."""
    user = _user()
    sid = uuid.uuid4()
    done = _maze_session_row(user.id, status="completed", session_id=sid)
    result = _maze_result_row(sid, {"game": "maze_race"})
    session = RecordingSession(
        script=[
            FakeResult(rows=[]),  # state gone
            done,  # sessions.get_by_id
            FakeResult(rows=[result]),  # results.get_by_session
        ]
    )
    svc = MiniappGameService(session)

    view = await svc.get_state(session_id=sid, user_id=user.id)

    assert view["finished"] is True
    assert view["difficulty"] == "medium"  # safe default grid
    assert view["maze"]["rows"] == 13 and view["maze"]["cols"] == 13
    assert view["result"]["elapsed_ms"] is None
    assert view["result"]["moves"] is None


async def test_get_state_decodes_stored_walls_array():
    """Regression: `_start_maze` stores walls as the raw bitmask list, but
    the reader decoded it via `deserialize_maze` (dict-only) -> TypeError
    -> unhandled 500 when resuming an active maze."""
    user = _user()
    sid = uuid.uuid4()
    state = _maze_state(user.id, sid, moves=3)
    session = RecordingSession(script=[FakeResult(rows=[state])])
    svc = MiniappGameService(session)

    view = await svc.get_state(session_id=sid, user_id=user.id)

    assert view["finished"] is False
    assert view["moves"] == 3 and view["attempts_used"] == 3
    assert view["maze"]["rows"] == 13 and view["maze"]["cols"] == 13
    assert view["player"] == {"r": 0, "c": 0}


async def test_direction_applies_move_on_stored_walls_array():
    """Movement on a production-shaped state (walls as int list) works and
    persists the new position."""
    user = _user()
    sid = uuid.uuid4()
    state = _maze_state(user.id, sid)
    session = RecordingSession(script=[FakeResult(rows=[state])])
    svc = MiniappGameService(session)

    view = await svc.direction(
        session_id=sid, user_id=user.id, direction="right",
        client_move_id="m1",
    )

    assert view["player"] == {"r": 0, "c": 1}
    assert view["moves"] == 1 and view["attempts_used"] == 1
    assert view["finished"] is False
    assert session.flushes == 1


async def test_missing_maze_state_on_unfinished_session_404s():
    """No state row + session not completed -> handled 404, unchanged."""
    user = _user()
    sid = uuid.uuid4()
    started = _maze_session_row(user.id, status="started", session_id=sid)
    session = RecordingSession(script=[FakeResult(rows=[]), started])
    svc = MiniappGameService(session)

    with pytest.raises(NotFoundError):
        await svc.get_state(session_id=sid, user_id=user.id)
