"""Perfect Second: pure rules, service flows, routes. No real DB/Telegram."""
import random
import uuid
from datetime import date

import pytest

from brainrush.db.errors import NotFoundError
from brainrush.db.models import (
    DailyActivity,
    GameResult,
    GameSession,
    PlayerProfile,
    User,
    WebappGameState,
)
from brainrush.game import perfect_second as perfect
from brainrush.services.miniapp import (
    CATALOG,
    GAME_TYPE_PERFECT_SECOND,
    MiniappGameService,
)
from tests.test_repositories import FakeResult, RecordingSession


def _user():
    user = User(telegram_id=7001, username="perfect", display_name="Perfect P")
    user.id = uuid.uuid4()
    return user


def _profile(user_id, total_xp=0):
    profile = PlayerProfile(
        user_id=user_id, total_xp=total_xp, current_level=1, games_played=0,
        wins=0, losses=0, current_streak=0, longest_streak=0,
    )
    profile.id = uuid.uuid4()
    return profile


def _perfect_state(user_id, session_id, difficulty="medium", target_ms=5500):
    row = WebappGameState(
        user_id=user_id, session_id=session_id, game_type="perfect_second",
        difficulty=difficulty, secret=target_ms, max_attempts=1, guesses=[],
    )
    row.id = uuid.uuid4()
    return row


def _session_row(user_id, status="started"):
    row = GameSession(user_id=user_id, game_type="perfect_second", status=status)
    row.id = uuid.uuid4()
    return row


def _result_row(session_id, score=0, outcome="win", xp=100, target_ms=5500,
                actual_ms=5500.0, error_ms=0.0):
    row = GameResult(
        session_id=session_id, score=score, outcome=outcome,
        xp_earned=xp,
        result_metadata={
            "game": "perfect_second",
            "difficulty": "medium",
            "target_ms": target_ms,
            "actual_ms": actual_ms,
            "error_ms": error_ms,
            "error_percent": 0.0,
            "accuracy_percent": 100.0,
        },
    )
    row.id = uuid.uuid4()
    return row


# --- pure rules ---------------------------------------------------------------

def test_target_ranges_steps_and_positivity():
    cases = {
        "easy": (3_000, 15_000, 1_000),
        "medium": (3_000, 12_000, 500),
        "hard": (2_000, 10_000, 10),
    }
    assert set(perfect.PERFECT_DIFFICULTIES) == set(cases)
    for did, (lo, hi, step) in cases.items():
        cfg = perfect.PERFECT_DIFFICULTIES[did]
        assert (cfg.min_target_ms, cfg.max_target_ms, cfg.step_ms) == (lo, hi, step)
        seen = {perfect.roll_target_ms(cfg, random.Random(1234 + i))
                for i in range(50)}
        assert len(seen) > 1  # fresh randomness, no fixed sequence
        for target in seen:
            assert lo <= target <= hi
            assert target > 0
            assert (target - lo) % step == 0


def test_medium_never_hundredths_and_easy_whole_seconds():
    medium = [perfect.roll_target_ms(perfect.PERFECT_DIFFICULTIES["medium"],
                                     random.Random(i)) for i in range(100)]
    assert all(t % 500 == 0 for t in medium)
    assert any(t % 1000 != 0 for t in medium)  # half-seconds actually occur
    easy = [perfect.roll_target_ms(perfect.PERFECT_DIFFICULTIES["easy"],
                                   random.Random(i)) for i in range(100)]
    assert all(t % 1000 == 0 for t in easy)


def test_xp_table_and_bounds():
    assert perfect.xp_for_accuracy(100.0) == 100
    assert perfect.xp_for_accuracy(90.0) == 90
    assert perfect.xp_for_accuracy(70.0) == 70
    assert perfect.xp_for_accuracy(50.0) == 50
    assert perfect.xp_for_accuracy(10.0) == 10
    assert perfect.xp_for_accuracy(0.0) == 0
    # Halfway cases round upward.
    assert perfect.xp_for_accuracy(85.0) == 90
    assert perfect.xp_for_accuracy(95.0) == 100
    assert perfect.xp_for_accuracy(5.0) == 10
    assert perfect.xp_for_accuracy(84.9) == 80
    # Clamp: never negative, never above 100.
    assert perfect.xp_for_accuracy(150.0) == 100
    assert perfect.xp_for_accuracy(-20.0) == 0


def test_score_result_proportional_and_unrounded():
    target = 10_000
    assert perfect.score_result(target_ms=target, actual_ms=10_000.0) == {
        "error_ms": 0.0, "error_percent": 0.0, "accuracy_percent": 100.0,
        "score_ms": 0, "xp": 100, "won": True,
    }
    ten = perfect.score_result(target_ms=target, actual_ms=9_000.0)
    assert ten["xp"] == 90 and ten["won"] is True
    assert perfect.score_result(target_ms=target, actual_ms=7_000.0)["xp"] == 70
    assert perfect.score_result(target_ms=target, actual_ms=5_000.0)["xp"] == 50
    zero = perfect.score_result(target_ms=target, actual_ms=0.0)
    assert zero["xp"] == 0 and zero["won"] is False
    over = perfect.score_result(target_ms=target, actual_ms=25_000.0)
    assert over["xp"] == 0 and over["won"] is False
    # Full measured precision: a 0.4 ms miss is a 0.4 ms error, not 0.
    fine = perfect.score_result(target_ms=5_000, actual_ms=5_000.4)
    assert fine["error_ms"] == pytest.approx(0.4)
    assert fine["xp"] == 100
    with pytest.raises(ValueError):
        perfect.score_result(target_ms=0, actual_ms=1.0)
    with pytest.raises(ValueError):
        perfect.score_result(target_ms=-5, actual_ms=1.0)


def test_win_boundary_exact_ten_percent():
    # Exactly 10% error still wins (multiplicative comparison, no float drift).
    assert perfect.score_result(target_ms=7_000, actual_ms=6_300.0)["won"] is True
    assert perfect.score_result(target_ms=7_000, actual_ms=6_299.0)["won"] is False


def test_parse_actual_ms_bounds():
    assert perfect.parse_actual_ms(5_000) == 5_000.0
    assert perfect.parse_actual_ms(5_000.25) == 5_000.25
    assert perfect.parse_actual_ms(0) == 0.0
    for bad in (True, False, "5000", None, [1], float("nan"),
                float("inf"), -1, -0.5, perfect.MAX_ACTUAL_MS + 1):
        with pytest.raises(ValueError):
            perfect.parse_actual_ms(bad)


def test_match_target_deterministic_shared_and_valid():
    import uuid as _uuid

    ids = [_uuid.UUID(int=i) for i in range(1, 11)]
    for did in ("easy", "medium", "hard"):
        cfg = perfect.PERFECT_DIFFICULTIES[did]
        targets = {perfect.match_target_ms(i, did) for i in ids}
        assert len(targets) > 1  # fresh per match
        for target in targets:
            assert cfg.min_target_ms <= target <= cfg.max_target_ms
            assert (target - cfg.min_target_ms) % cfg.step_ms == 0
    mid = _uuid.uuid4()
    assert perfect.match_target_ms(mid, "medium") == perfect.match_target_ms(mid, "medium")
    with pytest.raises(ValueError):
        perfect.match_target_ms(mid, "extreme")


# --- service flows ------------------------------------------------------------

async def test_perfect_start_returns_visible_target(monkeypatch):
    monkeypatch.setattr(
        "brainrush.services.miniapp.perfect.roll_target_ms", lambda config: 7000
    )
    user = _user()
    session = RecordingSession(script=[
        FakeResult(rowcount=0),  # expire sweep: nothing stale
        user,
        FakeResult(rows=[]),  # no active states
    ])
    svc = MiniappGameService(session)
    view = await svc.start_game(
        user_id=user.id, difficulty="easy", game_type="perfect_second"
    )
    assert view["game_type"] == "perfect_second"
    assert view["target_ms"] == 7000  # target visible during the attempt
    assert view["max_attempts"] == 1 and view["attempts_left"] == 1
    assert view["finished"] is False
    assert "secret" not in view
    assert session.commits == 0


async def test_perfect_start_rejects_bad_difficulty():
    svc = MiniappGameService(RecordingSession())
    with pytest.raises(ValueError):
        await svc.start_game(
            user_id=uuid.uuid4(), game_type="perfect_second", difficulty="extreme"
        )


async def test_perfect_stop_win_awards_server_computed_xp():
    user = _user()
    sid = uuid.uuid4()
    state = _perfect_state(user.id, sid, target_ms=5500)
    started = _session_row(user.id)
    done = _session_row(user.id, status="completed")
    profile = _profile(user.id, total_xp=100)
    activity = DailyActivity(user_id=user.id, activity_date=date(2026, 1, 1),
                             games_played=1, xp_earned=100)
    session = RecordingSession(script=[
        FakeResult(rows=[state]),
        started,
        FakeResult(rowcount=1),
        done,
        FakeResult(rowcount=1),
        FakeResult(rows=[profile]),
        FakeResult(rowcount=1),
        FakeResult(rows=[profile]),
        FakeResult(rows=[]),
        FakeResult(rowcount=1),
        FakeResult(rows=[activity]),
        FakeResult(rowcount=1),
        FakeResult(rows=[activity]),
    ])
    svc = MiniappGameService(session)
    view = await svc.stop_perfect(
        session_id=sid, user_id=user.id, actual_ms=5500.0,
        client_submission_id="stop-1",
    )
    assert view["finished"] is True
    assert view["result"]["outcome"] == "win"
    assert view["result"]["score"] == 0
    assert view["result"]["xp_earned"] == 100
    assert view["result"]["target_ms"] == 5500
    assert view["result"]["actual_ms"] == 5500.0
    assert view["result"]["error_ms"] == 0.0
    assert view["result"]["accuracy_percent"] == 100.0
    assert session.deleted == [state]
    assert session.commits == 0


async def test_perfect_stop_partial_error_proportional_xp():
    user = _user()
    sid = uuid.uuid4()
    state = _perfect_state(user.id, sid, target_ms=10_000)
    started = _session_row(user.id)
    done = _session_row(user.id, status="completed")
    profile = _profile(user.id, total_xp=70)
    activity = DailyActivity(user_id=user.id, activity_date=date(2026, 1, 1),
                             games_played=1, xp_earned=70)
    session = RecordingSession(script=[
        FakeResult(rows=[state]),
        started,
        FakeResult(rowcount=1),
        done,
        FakeResult(rowcount=1),
        FakeResult(rows=[profile]),
        FakeResult(rowcount=1),
        FakeResult(rows=[profile]),
        FakeResult(rows=[]),
        FakeResult(rowcount=1),
        FakeResult(rows=[activity]),
        FakeResult(rowcount=1),
        FakeResult(rows=[activity]),
    ])
    svc = MiniappGameService(session)
    view = await svc.stop_perfect(
        session_id=sid, user_id=user.id, actual_ms=13_000.0,
        client_submission_id="stop-1",
    )
    assert view["result"]["outcome"] == "loss"  # 30% error misses the win bar
    assert view["result"]["score"] == 3_000
    assert view["result"]["xp_earned"] == 70
    assert view["result"]["accuracy_percent"] == pytest.approx(70.0)


async def test_perfect_stop_rejects_bad_input_and_foreign_games():
    user = _user()
    sid = uuid.uuid4()
    state = _perfect_state(user.id, sid)
    svc = MiniappGameService(RecordingSession(script=[FakeResult(rows=[state])]))
    with pytest.raises(ValueError):
        await svc.stop_perfect(session_id=sid, user_id=user.id,
                               actual_ms=-5, client_submission_id="s1")
    svc2 = MiniappGameService(RecordingSession())
    with pytest.raises(ValueError):
        await svc2.stop_perfect(session_id=sid, user_id=user.id,
                                actual_ms=1000, client_submission_id="  ")
    # A number-guessing state can never be stopped as Perfect Second.
    from tests.test_miniapp_service import _state as _num_state
    num_state = _num_state(user.id, sid)
    svc3 = MiniappGameService(RecordingSession(script=[FakeResult(rows=[num_state])]))
    with pytest.raises(ValueError):
        await svc3.stop_perfect(session_id=sid, user_id=user.id,
                                actual_ms=1000, client_submission_id="s1")


async def test_perfect_duplicate_stop_does_not_double_award():
    user = _user()
    sid = uuid.uuid4()
    state = _perfect_state(user.id, sid)
    started = _session_row(user.id)
    done = _session_row(user.id, status="completed")
    profile = _profile(user.id, total_xp=100)
    activity = DailyActivity(user_id=user.id, activity_date=date(2026, 1, 1),
                             games_played=1, xp_earned=100)
    result = _result_row(sid)
    session = RecordingSession(script=[
        FakeResult(rows=[state]),  # stop 1: locked state
        started,
        FakeResult(rowcount=1),
        done,
        FakeResult(rowcount=1),
        FakeResult(rows=[profile]),
        FakeResult(rowcount=1),
        FakeResult(rows=[profile]),
        FakeResult(rows=[]),
        FakeResult(rowcount=1),
        FakeResult(rows=[activity]),
        FakeResult(rowcount=1),
        FakeResult(rows=[activity]),
        # stop 2 (retry, same or new id): state gone -> replay stored result
        FakeResult(rows=[]),  # get_for_update -> None
        done,  # _replay: session row (completed, owned)
        FakeResult(rows=[result]),  # _replay: result row
    ])
    svc = MiniappGameService(session)
    first = await svc.stop_perfect(session_id=sid, user_id=user.id,
                                   actual_ms=5500.0, client_submission_id="s1")
    second = await svc.stop_perfect(session_id=sid, user_id=user.id,
                                    actual_ms=5500.0, client_submission_id="s1")
    assert first["result"]["xp_earned"] == 100
    assert second["result"]["xp_earned"] == 100
    assert second["result"]["target_ms"] == 5500
    assert len(session.deleted) == 1  # exactly one terminal write
    assert session.commits == 0


async def test_perfect_get_state_cancel_and_dashboard():
    user = _user()
    sid = uuid.uuid4()
    state = _perfect_state(user.id, sid)
    started = _session_row(user.id)
    done_abandoned = _session_row(user.id, status="abandoned")
    profile = _profile(user.id, total_xp=100)
    session = RecordingSession(script=[
        FakeResult(rows=[state]),  # get_state: locked state
        FakeResult(rows=[state]),  # cancel: locked state
        started,
        FakeResult(rowcount=1),
        done_abandoned,
        # dashboard reads
        FakeResult(rowcount=0),  # expire sweep: nothing stale
        user,
        FakeResult(rows=[profile]),
        FakeResult(rows=[]),
        FakeResult(rows=[3]),  # best number win
        FakeResult(rows=[5]),  # best color
        FakeResult(rows=[900]),  # best reflex score
        FakeResult(rows=[250]),  # best perfect error (ms, won games)
        FakeResult(rows=[0]),  # rank
        FakeResult(rows=[]),  # actives
    ])
    svc = MiniappGameService(session)
    view = await svc.get_state(session_id=sid, user_id=user.id)
    assert view["game_type"] == "perfect_second" and view["finished"] is False
    assert view["target_ms"] == 5500
    out = await svc.cancel(session_id=sid, user_id=user.id)
    assert out["status"] == "abandoned"
    dash = await svc.dashboard(user_id=user.id)
    assert dash["best_perfect_error_ms"] == 250
    assert dash["best_reflex_score"] == 900


async def test_perfect_match_linked_start_uses_shared_target():
    from types import SimpleNamespace

    user = _user()
    mid = uuid.uuid4()
    match = SimpleNamespace(id=mid, status="active",
                            game_type="perfect_second", difficulty="medium")
    seat = SimpleNamespace(match_id=mid, user_id=user.id)
    expected = perfect.match_target_ms(mid, "medium")
    session = RecordingSession(script=[
        FakeResult(rowcount=0),  # expire sweep
        user,
        match,  # match lookup (session.get)
        FakeResult(rows=[seat]),  # participant check
        FakeResult(rows=[]),  # no active states
    ])
    svc = MiniappGameService(session)
    view = await svc.start_game(
        user_id=user.id, difficulty="medium",
        game_type="perfect_second", match_id=mid,
    )
    assert view["target_ms"] == expected
    assert session.commits == 0


async def test_perfect_match_linked_start_rejects_mismatch():
    from types import SimpleNamespace

    user = _user()
    mid = uuid.uuid4()
    # Unknown match.
    svc = MiniappGameService(RecordingSession(script=[
        FakeResult(rowcount=0), user, None,
    ]))
    with pytest.raises(NotFoundError):
        await svc.start_game(user_id=user.id, difficulty="medium",
                             game_type="perfect_second", match_id=mid)
    # Match not started.
    lobby = SimpleNamespace(id=mid, status="lobby",
                            game_type="perfect_second", difficulty="medium")
    svc2 = MiniappGameService(RecordingSession(script=[
        FakeResult(rowcount=0), user, lobby,
    ]))
    from brainrush.db.errors import ConflictError
    with pytest.raises(ConflictError):
        await svc2.start_game(user_id=user.id, difficulty="medium",
                              game_type="perfect_second", match_id=mid)
    # Non-participant.
    active = SimpleNamespace(id=mid, status="active",
                             game_type="perfect_second", difficulty="medium")
    svc3 = MiniappGameService(RecordingSession(script=[
        FakeResult(rowcount=0), user, active, FakeResult(rows=[]),
    ]))
    with pytest.raises(NotFoundError):
        await svc3.start_game(user_id=user.id, difficulty="medium",
                              game_type="perfect_second", match_id=mid)
    # Smuggled difficulty / game.
    seat = SimpleNamespace(match_id=mid, user_id=user.id)
    svc4 = MiniappGameService(RecordingSession(script=[
        FakeResult(rowcount=0), user, active, FakeResult(rows=[seat]),
    ]))
    with pytest.raises(ValueError):
        await svc4.start_game(user_id=user.id, difficulty="hard",
                              game_type="perfect_second", match_id=mid)
    svc5 = MiniappGameService(RecordingSession(script=[
        FakeResult(rowcount=0), user, active, FakeResult(rows=[seat]),
    ]))
    with pytest.raises(ValueError):
        await svc5.start_game(user_id=user.id, difficulty="medium",
                              game_type="number_guessing", match_id=mid)


# --- routes -------------------------------------------------------------------

def test_perfect_routes_and_catalog(monkeypatch):
    from fastapi import Request
    from fastapi.testclient import TestClient

    from brainrush.api import routes
    from brainrush.api.app import create_app
    from brainrush.api.deps import get_session, get_verified_identity
    from brainrush.config import Settings

    settings = Settings(BOT_TOKEN="t",
                        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db")

    class Stub:
        instance = None

        def __init__(self, session):
            self.calls = []
            Stub.instance = self

        async def start_game(self, *, user_id, difficulty="hard",
                             game_type="number_guessing", match_id=None):
            self.calls.append(("start", game_type, difficulty, match_id))
            return {"session_id": "s1", "game_type": game_type, "finished": False}

        async def stop_perfect(self, *, session_id, user_id, actual_ms,
                               client_submission_id):
            self.calls.append(("stop", session_id, actual_ms, client_submission_id))
            return {"finished": True, "result": {"xp_earned": 100}}

        async def get_state(self, *, session_id, user_id):
            return {"finished": False}

    class _CM:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    app = create_app(settings, session_factory=_CM())

    async def fake_session(request: Request):
        yield object()

    async def fake_identity(request: Request):
        request.state.telegram_id = 1
        return {"user_id": uuid.uuid4(), "telegram_id": 1,
                "username": "p", "display_name": "P"}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_verified_identity] = fake_identity
    monkeypatch.setattr(routes, "MiniappGameService", Stub)
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-Telegram-Init-Data": "x"}

    started = client.post("/api/sessions", headers=headers,
                          json={"game_type": "perfect_second", "difficulty": "easy"})
    assert started.status_code == 200

    ok = client.post(f"/api/sessions/{uuid.uuid4()}/stop", headers=headers,
                     json={"actual_ms": 5123.4, "client_submission_id": "stop-1"})
    assert ok.status_code == 200
    assert Stub.instance.calls[-1][0] == "stop"

    catalog = client.get("/api/games", headers=headers).json()
    by_id = {g["id"]: g for g in catalog["games"]}
    entry = by_id["perfect_second"]
    assert entry["playable"] is True
    assert {d["id"] for d in entry["difficulties"]} == {"easy", "medium", "hard"}
    assert entry["difficulties"][0]["max_attempts"] == 1
    assert entry["xp_rules"]["hard"]["perfect"] == 100


def test_catalog_lists_four_playable_games():
    ids = [e["id"] for e in CATALOG if e["playable"]]
    assert ids == ["number_guessing", "color_sequence", "reflex_rush",
                   "perfect_second"]
    assert GAME_TYPE_PERFECT_SECOND == "perfect_second"
