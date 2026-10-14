"""Color Sequence: pure rules, service flows, routes. No real DB/Telegram."""
import uuid
from datetime import date

import pytest

from brainrush.db.errors import NotFoundError
from brainrush.db.models import DailyActivity, GameSession, PlayerProfile, User, WebappGameState
from brainrush.game import color_sequence as colors
from brainrush.services.miniapp import (
    CATALOG,
    GAME_TYPE_COLOR_SEQUENCE,
    MiniappGameService,
)
from tests.test_repositories import FakeResult, RecordingSession


def _user():
    user = User(telegram_id=7001, username="chroma", display_name="Chroma")
    user.id = uuid.uuid4()
    return user


def _profile(user_id, total_xp=0):
    profile = PlayerProfile(
        user_id=user_id, total_xp=total_xp, current_level=1, games_played=0,
        wins=0, losses=0, current_streak=0, longest_streak=0,
    )
    profile.id = uuid.uuid4()
    return profile


def _color_state(user_id, session_id, sequence, position=0, level=None,
                 completed=0, log=None, difficulty="hard", max_attempts=7):
    data = {
        "sequence": list(sequence),
        "position": position,
        "level": level if level is not None else len(sequence),
        "levels_completed": completed,
        "log": list(log or []),
    }
    row = WebappGameState(
        user_id=user_id, session_id=session_id, game_type="color_sequence",
        difficulty=difficulty, secret=0, max_attempts=max_attempts,
        guesses=data,
    )
    row.id = uuid.uuid4()
    return row


def _session_row(user_id, status="started", game_type="color_sequence"):
    row = GameSession(user_id=user_id, game_type=game_type, status=status)
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


# --- pure rules ------------------------------------------------------------

def test_sequence_generation_and_config_ranges():
    for did, cfg in colors.COLOR_DIFFICULTIES.items():
        assert cfg.start_length < cfg.max_level
        seq = colors.new_sequence(cfg.start_length, rng=__import__("random").Random(7))
        assert len(seq) == cfg.start_length
        assert all(c in colors.COLORS for c in seq)
    assert set(colors.COLOR_DIFFICULTIES) == {"easy", "medium", "hard"}


def test_tap_validation_and_check():
    assert colors.parse_tap(2) == 2
    for bad in (-1, 4, True, "2", None, 1.5):
        with pytest.raises(colors.InvalidTapError):
            colors.parse_tap(bad)
    assert colors.check_tap([0, 2, 1], 0, 0) is True
    assert colors.check_tap([0, 2, 1], 1, 0) is False
    with pytest.raises(colors.InvalidTapError):
        colors.check_tap([0], 5, 0)


def test_color_xp_rule_documented_values():
    easy = colors.COLOR_DIFFICULTIES["easy"]
    assert colors.xp_for_color_result(levels_completed=8, won=True, config=easy) == 8 * 6 + 30
    assert colors.xp_for_color_result(levels_completed=5, won=False, config=easy) == 5 * 6
    assert colors.xp_for_color_result(levels_completed=0, won=False, config=easy) == 0
    hard = colors.COLOR_DIFFICULTIES["hard"]
    assert colors.xp_for_color_result(levels_completed=12, won=True, config=hard) == 12 * 10 + 80


def test_catalog_registers_color_sequence_playable():
    by_id = {g["id"]: g for g in CATALOG}
    entry = by_id["color_sequence"]
    assert entry["playable"] is True
    assert {d["id"] for d in entry["difficulties"]} == {"easy", "medium", "hard"}
    assert by_id["number_guessing"]["playable"] is True
    assert by_id["memory_match"]["playable"] is False


# --- service flows ----------------------------------------------------------

async def test_color_start_creates_prefixed_view(monkeypatch):
    monkeypatch.setattr(
        "brainrush.services.miniapp.colors.new_sequence", lambda n, rng=None: [0, 1, 2]
    )
    user = _user()
    session = RecordingSession(script=[user, FakeResult(rows=[])])
    svc = MiniappGameService(session)
    view = await svc.start_game(
        user_id=user.id, difficulty="easy", game_type="color_sequence"
    )

    assert view["game_type"] == "color_sequence"
    assert view["display"] == [0, 1, 2]  # start_length 3 prefix only
    assert view["position"] == 0 and view["level"] == 3
    assert view["finished"] is False
    assert _no_secret_leak(view)
    assert session.commits == 0


async def test_color_start_rejects_unknown_game_and_difficulty():
    svc = MiniappGameService(RecordingSession())
    with pytest.raises(ValueError):
        await svc.start_game(user_id=uuid.uuid4(), game_type="memory_match")
    with pytest.raises(ValueError):
        await svc.start_game(
            user_id=uuid.uuid4(), game_type="color_sequence", difficulty="extreme"
        )


async def test_color_correct_taps_advance_without_new_level():
    user = _user()
    sid = uuid.uuid4()
    state = _color_state(user.id, sid, sequence=[0, 2, 1])
    session = RecordingSession(script=[FakeResult(rows=[state])])
    svc = MiniappGameService(session)

    view = await svc.tap(
        session_id=sid, user_id=user.id, color=0, client_move_id="m1"
    )
    assert view["position"] == 1 and view["level"] == 3
    assert view["display"] == [0, 2, 1]
    assert view["finished"] is False
    assert _no_secret_leak(view)


async def test_color_wrong_tap_ends_run_with_score_and_xp():
    user = _user()
    sid = uuid.uuid4()
    # two levels already completed, failing on level 3 -> score 2
    state = _color_state(user.id, sid, sequence=[0, 2, 1], position=0,
                         level=3, completed=2,
                         log=[{"id": "a", "value": 0, "hit": True}])
    started = _session_row(user.id)
    done = _session_row(user.id, status="completed")
    profile = _profile(user.id, total_xp=12)  # 2 levels * 6 xp (easy default? hard: 2*10)
    activity = DailyActivity(user_id=user.id, activity_date=date(2026, 1, 1),
                             games_played=1, xp_earned=20)
    session = RecordingSession(
        script=[
            FakeResult(rows=[state]),  # tap: locked state (hard: 2*10=20)
            started,  # finish: get session
            FakeResult(rowcount=1),  # finish: update
            done,  # finish: re-get
            # results.record: add/flush
            FakeResult(rowcount=1),  # record_game: update
            FakeResult(rows=[profile]),  # record_game: re-select
            FakeResult(rowcount=1),  # set_level: update
            FakeResult(rows=[profile]),  # set_level: re-select
            FakeResult(rows=[]),  # activities: get (absent)
            FakeResult(rowcount=1),  # activities: upsert
            FakeResult(rows=[activity]),  # activities: re-select
            FakeResult(rowcount=1),  # activities: bump
            FakeResult(rows=[activity]),  # activities: final select
            # states.delete
        ]
    )
    svc = MiniappGameService(session)
    view = await svc.tap(
        session_id=sid, user_id=user.id, color=3, client_move_id="m2"
    )

    assert view["finished"] is True
    assert view["result"]["outcome"] == "loss"
    assert view["result"]["score"] == 2
    assert view["result"]["xp_earned"] == 20
    assert view["result"]["secret"] is None
    assert session.deleted == [state]
    assert session.commits == 0


async def test_color_level_up_appends_server_side():
    user = _user()
    sid = uuid.uuid4()
    state = _color_state(user.id, sid, sequence=[1, 1, 1], position=2,
                         level=3, completed=0, log=[])
    session = RecordingSession(script=[FakeResult(rows=[state])])
    svc = MiniappGameService(session)

    view = await svc.tap(
        session_id=sid, user_id=user.id, color=1, client_move_id="m1"
    )
    assert view["finished"] is False
    assert view["level"] == 4 and len(view["display"]) == 4
    assert view["position"] == 0


async def test_color_win_at_max_level():
    user = _user()
    sid = uuid.uuid4()
    cfg_max, xp_per, bonus = 8, 6, 30  # easy
    seq = [0] * 8
    log = [{"id": f"m{i}", "value": 0, "hit": True} for i in range(7)]
    state = _color_state(user.id, sid, sequence=seq, position=7,
                         level=8, completed=7, log=log,
                         difficulty="easy", max_attempts=8)
    started = _session_row(user.id)
    done = _session_row(user.id, status="completed")
    profile = _profile(user.id, total_xp=cfg_max * xp_per + bonus)
    activity = DailyActivity(user_id=user.id, activity_date=date(2026, 1, 1),
                             games_played=1, xp_earned=cfg_max * xp_per + bonus)
    session = RecordingSession(
        script=[
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
        ]
    )
    svc = MiniappGameService(session)
    view = await svc.tap(
        session_id=sid, user_id=user.id, color=0, client_move_id="m8"
    )
    assert view["finished"] is True
    assert view["result"]["outcome"] == "win"
    assert view["result"]["score"] == 8
    assert view["result"]["xp_earned"] == 8 * 6 + 30


async def test_color_retry_same_id_and_invalid_and_foreign():
    user = _user()
    sid = uuid.uuid4()
    state = _color_state(user.id, sid, sequence=[0, 2, 1],
                         log=[{"id": "m1", "value": 0, "hit": True}])
    session = RecordingSession(script=[FakeResult(rows=[state])])
    svc = MiniappGameService(session)
    view = await svc.tap(
        session_id=sid, user_id=user.id, color=0, client_move_id="m1"
    )
    assert view["position"] == 0  # replayed, nothing consumed

    with pytest.raises(ValueError):
        await MiniappGameService(RecordingSession()).tap(
            session_id=sid, user_id=user.id, color=9, client_move_id="m2"
        )

    foreign_state = _color_state(uuid.uuid4(), sid, sequence=[0])
    foreign_session = _session_row(uuid.uuid4())
    session3 = RecordingSession(
        script=[FakeResult(rows=[foreign_state]), foreign_session]
    )
    with pytest.raises(NotFoundError):
        await MiniappGameService(session3).tap(
            session_id=sid, user_id=user.id, color=0, client_move_id="m3"
        )


async def test_color_cancel_and_get_state_branch():
    user = _user()
    sid = uuid.uuid4()
    state = _color_state(user.id, sid, sequence=[3, 1])
    started = _session_row(user.id)
    done = _session_row(user.id, status="abandoned")
    session = RecordingSession(
        script=[
            FakeResult(rows=[state]),  # get_state: locked state
            FakeResult(rows=[state]),  # cancel: locked state
            started,  # abandon: get
            FakeResult(rowcount=1),  # abandon: update
            done,  # abandon: re-get
        ]
    )
    svc = MiniappGameService(session)
    view = await svc.get_state(session_id=sid, user_id=user.id)
    assert view["display"] == [3, 1] and view["finished"] is False
    assert _no_secret_leak(view)
    out = await svc.cancel(session_id=sid, user_id=user.id)
    assert out["status"] == "abandoned"
    assert len(session.deleted) == 1


async def test_number_guess_rejects_color_session_and_vice_versa():
    user = _user()
    sid = uuid.uuid4()
    color_state = _color_state(user.id, sid, sequence=[0])
    num_state_row = uuid.uuid4()
    from brainrush.db.models import WebappGameState as _W
    num_state = _W(user_id=user.id, session_id=num_state_row,
                   game_type="number_guessing", difficulty="hard",
                   secret=42, max_attempts=7, guesses=[])
    svc = MiniappGameService(RecordingSession(
        script=[FakeResult(rows=[color_state])]))
    with pytest.raises(ValueError):
        await svc.guess(session_id=sid, user_id=user.id, value=42,
                        client_guess_id="c1")
    svc2 = MiniappGameService(RecordingSession(
        script=[FakeResult(rows=[num_state])]))
    with pytest.raises(ValueError):
        await svc2.tap(session_id=num_state_row, user_id=user.id, color=1,
                       client_move_id="m1")
