"""Reflex Rush: pure rules, service flows, routes. No real DB/Telegram."""
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
from brainrush.game import reflex_rush as reflex
from brainrush.services.miniapp import (
    CATALOG,
    GAME_TYPE_REFLEX_RUSH,
    MiniappGameService,
)
from tests.test_repositories import FakeResult, RecordingSession


def _user():
    user = User(telegram_id=8001, username="reflex", display_name="Reflex R")
    user.id = uuid.uuid4()
    return user


def _profile(user_id, total_xp=0):
    profile = PlayerProfile(
        user_id=user_id, total_xp=total_xp, current_level=1, games_played=0,
        wins=0, losses=0, current_streak=0, longest_streak=0,
    )
    profile.id = uuid.uuid4()
    return profile


def _reflex_state(user_id, session_id, difficulty="medium"):
    row = WebappGameState(
        user_id=user_id, session_id=session_id, game_type="reflex_rush",
        difficulty=difficulty, secret=0, max_attempts=5, guesses=[],
    )
    row.id = uuid.uuid4()
    return row


def _session_row(user_id, status="started", game_type="reflex_rush"):
    row = GameSession(user_id=user_id, game_type=game_type, status=status)
    row.id = uuid.uuid4()
    return row


def _result_row(session_id, score=1000, outcome="win", xp=50):
    row = GameResult(
        session_id=session_id, score=score, outcome=outcome,
        xp_earned=xp,
        result_metadata={
            "game": "reflex_rush", "difficulty": "medium",
            "rounds": [
                {"reaction_ms": 200, "false_start": False},
                {"reaction_ms": 250, "false_start": False},
                {"reaction_ms": 300, "false_start": False},
                {"reaction_ms": 220, "false_start": False},
                {"reaction_ms": 240, "false_start": False},
            ],
            "avg_ms": 242, "best_ms": 200, "false_starts": 0,
            "valid_taps": 5,
        },
    )
    row.id = uuid.uuid4()
    return row


# --- pure rules ------------------------------------------------------------

def test_difficulty_wait_windows_match_spec():
    assert set(reflex.REFLEX_DIFFICULTIES) == {"easy", "medium", "hard"}
    easy = reflex.REFLEX_DIFFICULTIES["easy"]
    medium = reflex.REFLEX_DIFFICULTIES["medium"]
    hard = reflex.REFLEX_DIFFICULTIES["hard"]
    # Easy: one fixed wait every round (predictable).
    assert easy.wait_min_ms == easy.wait_max_ms
    # Normal: varies inside a defined range.
    assert medium.wait_min_ms < medium.wait_max_ms
    # Hard: randomized inside a WIDER range than Normal.
    assert (hard.wait_max_ms - hard.wait_min_ms) > (medium.wait_max_ms - medium.wait_min_ms)
    # Easy floor stays slower than hard's fastest possible wait.
    assert easy.wait_min_ms > hard.wait_min_ms
    rng = random.Random(3)
    for did, cfg in reflex.REFLEX_DIFFICULTIES.items():
        w = reflex.random_wait_ms(cfg, rng)
        assert cfg.wait_min_ms <= w <= cfg.wait_max_ms
    # Easy is deterministic: same wait every round.
    assert len({reflex.random_wait_ms(easy, random.Random(i)) for i in range(20)}) == 1


def test_reaction_validation():
    assert reflex.parse_reaction_ms(250) == 250
    for bad in (0, -5, 10_001, True, "250", None, 1.5):
        with pytest.raises(ValueError):
            reflex.parse_reaction_ms(bad)


def test_validate_rounds_count_and_shape():
    cfg = reflex.REFLEX_DIFFICULTIES["medium"]
    good = [{"reaction_ms": 200, "false_start": False}] * 5
    assert len(reflex.validate_rounds(good, cfg)) == 5
    with pytest.raises(ValueError):
        reflex.validate_rounds(good[:4], cfg)
    with pytest.raises(ValueError):
        reflex.validate_rounds([{"reaction_ms": None, "false_start": False}] * 5, cfg)
    with pytest.raises(ValueError):
        reflex.validate_rounds([{"reaction_ms": 200, "false_start": True}] * 5, cfg)
    with pytest.raises(ValueError):
        reflex.validate_rounds([{"reaction_ms": 0, "false_start": False}] * 5, cfg)


def test_false_start_scores_zero_and_consumes_round():
    cfg = reflex.REFLEX_DIFFICULTIES["medium"]
    assert reflex.round_points(reaction_ms=None, false_start=True, config=cfg) == 0
    assert reflex.round_xp(reaction_ms=None, false_start=True, config=cfg) == 0
    rounds = reflex.validate_rounds(
        [{"reaction_ms": None, "false_start": True}]
        + [{"reaction_ms": 200, "false_start": False}] * 4,
        cfg,
    )
    agg = reflex.aggregate(rounds, cfg)
    assert agg["false_starts"] == 1
    assert agg["valid_taps"] == 4
    assert agg["best_ms"] == 200
    # False start never leaks into the average.
    assert agg["avg_ms"] == 200


def test_scoring_rewards_faster_taps():
    cfg = reflex.REFLEX_DIFFICULTIES["medium"]
    fast = reflex.aggregate(
        reflex.validate_rounds([{"reaction_ms": 180, "false_start": False}] * 5, cfg), cfg
    )
    slow = reflex.aggregate(
        reflex.validate_rounds([{"reaction_ms": 600, "false_start": False}] * 5, cfg), cfg
    )
    assert fast["score"] > slow["score"]
    assert fast["xp"] > slow["xp"]
    assert fast["won"] is True
    assert slow["won"] is False  # avg 600 > medium win_avg 550


def test_difficulty_specific_win_thresholds():
    easy = reflex.REFLEX_DIFFICULTIES["easy"]
    hard = reflex.REFLEX_DIFFICULTIES["hard"]
    mid_rounds = [{"reaction_ms": 600, "false_start": False}] * 5
    assert reflex.aggregate(reflex.validate_rounds(mid_rounds, easy), easy)["won"] is True
    assert reflex.aggregate(reflex.validate_rounds(mid_rounds, hard), hard)["won"] is False


def test_all_false_starts_is_loss_with_zero_score():
    cfg = reflex.REFLEX_DIFFICULTIES["medium"]
    rounds = reflex.validate_rounds(
        [{"reaction_ms": None, "false_start": True}] * 5, cfg
    )
    agg = reflex.aggregate(rounds, cfg)
    assert agg["won"] is False
    assert agg["score"] == 0 and agg["xp"] == 0
    assert agg["avg_ms"] is None and agg["best_ms"] is None


# --- service flows ----------------------------------------------------------

def test_catalog_registers_reflex_playable_and_preserves_others():
    by_id = {g["id"]: g for g in CATALOG}
    entry = by_id["reflex_rush"]
    assert entry["playable"] is True
    assert {d["id"] for d in entry["difficulties"]} == {"easy", "medium", "hard"}
    assert by_id["number_guessing"]["playable"] is True
    assert by_id["color_sequence"]["playable"] is True
    assert by_id["memory_match"]["playable"] is False


async def test_reflex_start_returns_public_view_without_secret():
    user = _user()
    session = RecordingSession(script=[
        FakeResult(rowcount=0),  # expire sweep: nothing stale
        user,
        FakeResult(rows=[]),
    ])
    svc = MiniappGameService(session)
    view = await svc.start_game(user_id=user.id, difficulty="medium", game_type="reflex_rush")
    assert view["game_type"] == "reflex_rush"
    assert view["rounds_total"] == 5
    assert view["finished"] is False
    assert "secret" not in view
    assert session.commits == 0


async def test_reflex_start_rejects_bad_difficulty_and_game():
    svc = MiniappGameService(RecordingSession())
    with pytest.raises(ValueError):
        await svc.start_game(user_id=uuid.uuid4(), game_type="reflex_rush", difficulty="extreme")
    with pytest.raises(ValueError):
        await svc.start_game(user_id=uuid.uuid4(), game_type="memory_match")


async def test_reflex_finish_win_awards_server_computed_xp():
    user = _user()
    sid = uuid.uuid4()
    state = _reflex_state(user.id, sid, difficulty="medium")
    started = _session_row(user.id)
    done = _session_row(user.id, status="completed")
    cfg = reflex.REFLEX_DIFFICULTIES["medium"]
    rounds = [{"reaction_ms": 200, "false_start": False}] * 5
    agg = reflex.aggregate(reflex.validate_rounds(rounds, cfg), cfg)
    assert agg["won"] is True
    profile = _profile(user.id, total_xp=agg["xp"])
    activity = DailyActivity(user_id=user.id, activity_date=date(2026, 1, 1),
                             games_played=1, xp_earned=agg["xp"])
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
    view = await svc.finish_reflex(
        session_id=sid, user_id=user.id, rounds=rounds, client_submission_id="sub-1"
    )
    assert view["finished"] is True
    assert view["result"]["outcome"] == "win"
    assert view["result"]["score"] == agg["score"]
    assert view["result"]["xp_earned"] == agg["xp"]
    assert view["result"]["avg_ms"] == agg["avg_ms"]
    assert view["result"]["best_ms"] == 200
    assert session.deleted == [state]
    assert session.commits == 0


async def test_reflex_finish_rejects_bad_rounds_and_ids():
    user = _user()
    sid = uuid.uuid4()
    state = _reflex_state(user.id, sid)
    svc = MiniappGameService(RecordingSession(script=[FakeResult(rows=[state])]))
    with pytest.raises(ValueError):
        await svc.finish_reflex(session_id=sid, user_id=user.id,
                                rounds=[{"reaction_ms": 200, "false_start": False}] * 4,
                                client_submission_id="s1")
    svc2 = MiniappGameService(RecordingSession())
    with pytest.raises(ValueError):
        await svc2.finish_reflex(session_id=sid, user_id=user.id,
                                 rounds=[{"reaction_ms": 200, "false_start": False}] * 5,
                                 client_submission_id="  ")


async def test_reflex_duplicate_submission_does_not_double_award():
    user = _user()
    sid = uuid.uuid4()
    state = _reflex_state(user.id, sid)
    started = _session_row(user.id)
    done = _session_row(user.id, status="completed")
    cfg = reflex.REFLEX_DIFFICULTIES["medium"]
    rounds = [{"reaction_ms": 250, "false_start": False}] * 5
    agg = reflex.aggregate(reflex.validate_rounds(rounds, cfg), cfg)
    profile = _profile(user.id, total_xp=agg["xp"])
    activity = DailyActivity(user_id=user.id, activity_date=date(2026, 1, 1),
                             games_played=1, xp_earned=agg["xp"])
    result = _result_row(sid, score=agg["score"],
                         outcome="win" if agg["won"] else "loss", xp=agg["xp"])
    session = RecordingSession(script=[
        FakeResult(rows=[state]),  # finish 1: locked state
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
        # finish 2 (retry, same or new id): state gone -> replay stored result
        FakeResult(rows=[]),  # get_for_update -> None
        done,  # _replay: session row (completed, owned)
        FakeResult(rows=[result]),  # _replay: result row
    ])
    svc = MiniappGameService(session)
    first = await svc.finish_reflex(session_id=sid, user_id=user.id,
                                    rounds=rounds, client_submission_id="sub-1")
    second = await svc.finish_reflex(session_id=sid, user_id=user.id,
                                     rounds=rounds, client_submission_id="sub-1")
    assert first["result"]["xp_earned"] == agg["xp"]
    assert second["result"]["xp_earned"] == agg["xp"]
    assert len(session.deleted) == 1  # only the first submission wrote


async def test_reflex_foreign_session_gets_404():
    owner = uuid.uuid4()
    intruder = uuid.uuid4()
    sid = uuid.uuid4()
    state = _reflex_state(owner, sid)
    foreign_session = _session_row(owner)
    session = RecordingSession(script=[FakeResult(rows=[state]), foreign_session])
    svc = MiniappGameService(session)
    with pytest.raises(NotFoundError):
        await svc.finish_reflex(
            session_id=sid, user_id=intruder,
            rounds=[{"reaction_ms": 200, "false_start": False}] * 5,
            client_submission_id="s1",
        )


async def test_reflex_wrong_endpoint_rejected():
    user = _user()
    sid = uuid.uuid4()
    num_state_row = uuid.uuid4()
    from brainrush.db.models import WebappGameState as _W
    num_state = _W(user_id=user.id, session_id=num_state_row,
                   game_type="number_guessing", difficulty="hard",
                   secret=42, max_attempts=7, guesses=[])
    svc = MiniappGameService(RecordingSession(script=[FakeResult(rows=[num_state])]))
    with pytest.raises(ValueError):
        await svc.finish_reflex(session_id=num_state_row, user_id=user.id,
                                rounds=[{"reaction_ms": 200, "false_start": False}] * 5,
                                client_submission_id="s1")
    reflex_state = _reflex_state(user.id, sid)
    svc2 = MiniappGameService(RecordingSession(script=[FakeResult(rows=[reflex_state])]))
    with pytest.raises(ValueError):
        await svc2.guess(session_id=sid, user_id=user.id, value=42, client_guess_id="c1")
    svc3 = MiniappGameService(RecordingSession(script=[FakeResult(rows=[reflex_state])]))
    with pytest.raises(ValueError):
        await svc3.tap(session_id=sid, user_id=user.id, color=1, client_move_id="m1")


async def test_reflex_get_state_and_cancel_and_dashboard():
    user = _user()
    sid = uuid.uuid4()
    state = _reflex_state(user.id, sid)
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
        FakeResult(rows=[900]),  # best reflex score (isolated per game_type)
        FakeResult(rows=[]),  # best perfect error (none yet)
        FakeResult(rows=[]),  # best maze time (none yet)
        FakeResult(rows=[0]),  # rank
        FakeResult(rows=[]),  # actives
    ])
    svc = MiniappGameService(session)
    view = await svc.get_state(session_id=sid, user_id=user.id)
    assert view["game_type"] == "reflex_rush" and view["finished"] is False
    out = await svc.cancel(session_id=sid, user_id=user.id)
    assert out["status"] == "abandoned"
    dash = await svc.dashboard(user_id=user.id)
    assert dash["best_reflex_score"] == 900
    assert dash["best_color_level"] == 5
    assert dash["best_win_attempts"] == 3


# --- routes -----------------------------------------------------------------

def test_reflex_routes_and_catalog(monkeypatch):
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

        async def start_game(self, *, user_id, difficulty="hard", game_type="number_guessing", match_id=None):
            self.calls.append(("start", game_type, difficulty))
            return {"session_id": "s1", "game_type": game_type, "finished": False}

        async def finish_reflex(self, *, session_id, user_id, rounds, client_submission_id):
            self.calls.append(("finish", session_id, len(rounds), client_submission_id))
            return {"finished": True, "result": {"xp_earned": 10}}

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
                "username": "r", "display_name": "R"}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_verified_identity] = fake_identity
    monkeypatch.setattr(routes, "MiniappGameService", Stub)
    client = TestClient(app, raise_server_exceptions=False)
    headers = {"X-Telegram-Init-Data": "x"}

    started = client.post("/api/sessions", headers=headers,
                          json={"game_type": "reflex_rush", "difficulty": "easy"})
    assert started.status_code == 200

    ok = client.post(f"/api/sessions/{uuid.uuid4()}/finish", headers=headers,
                     json={"rounds": [{"reaction_ms": 200, "false_start": False}] * 5,
                           "client_submission_id": "sub-1"})
    assert ok.status_code == 200

    short = client.post(f"/api/sessions/{uuid.uuid4()}/finish", headers=headers,
                        json={"rounds": [{"reaction_ms": 200, "false_start": False}] * 4,
                              "client_submission_id": "sub-1"})
    assert short.status_code == 422

    catalog = client.get("/api/games", headers=headers).json()
    by_id = {g["id"]: g for g in catalog["games"]}
    assert by_id["reflex_rush"]["playable"] is True
    assert {d["id"] for d in by_id["reflex_rush"]["difficulties"]} == {"easy", "medium", "hard"}
    assert by_id["number_guessing"]["playable"] is True
    assert by_id["color_sequence"]["playable"] is True
