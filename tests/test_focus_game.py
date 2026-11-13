"""Focus Rush falling-shapes arcade: engine rules + service validation."""
import random
import uuid

import pytest

from brainrush.db.models import WebappGameState
from brainrush.game import focus_rush as focus
from brainrush.services.miniapp import MiniappGameService
from tests.test_repositories import FakeResult, RecordingSession

NOW = 1_700_000_000_000


def _started(difficulty="easy", seed=7, now=NOW):
    rng = random.Random(seed)
    state = focus.new_state(difficulty, now, rng)
    focus.resume(state, now)
    # Past warm-up and the first guaranteed target, so a target is on screen.
    focus.advance(state, now + focus.WARMUP_MS + 400, rng)
    return state, rng


def _target(state, now=NOW + focus.WARMUP_MS + 400):
    """A target that has already entered the play area (not a scheduled one)."""
    return next(
        o for o in state["objects"]
        if focus.is_target_object(o) and o["spawned_at_ms"] <= now
    )


def _distractor(state):
    return next(o for o in state["objects"] if not focus.is_target_object(o))


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def test_new_run_starts_paused_with_three_lives():
    state = focus.new_state("medium", NOW)
    assert state["paused"] is True
    assert state["lives"] == focus.MAX_LIVES == 3
    assert state["score"] == 0 and state["objects"] == []
    assert state["target"]["color"] in focus.FOCUS_DIFFICULTIES["medium"].colors
    assert state["target"]["shape"] in focus.FOCUS_DIFFICULTIES["medium"].shapes


def test_resume_spawns_several_independent_objects():
    state, rng = _started("easy")
    focus.advance(state, NOW + 4_000, rng)
    visible = state["objects"]
    assert len(visible) >= 2  # multiple shapes fall at once, not one at a time
    assert len({o["id"] for o in visible}) == len(visible)
    assert len({o["x"] for o in visible}) >= 2  # independent horizontal lanes
    assert len({o["fall_ms"] for o in visible}) >= 2  # independent speeds
    assert all(0 <= o["x"] <= 1 for o in visible)
    assert all(o["spawned_at_ms"] <= NOW + 4_000 + focus.SPAWN_LOOKAHEAD_MS for o in visible)


def test_spawns_are_scheduled_ahead_but_not_tappable_early():
    state, rng = _started("easy")
    now = NOW + focus.WARMUP_MS + 400
    scheduled = [o for o in state["objects"] if o["spawned_at_ms"] > now]
    assert scheduled, "client should receive shapes before they enter the area"
    early = scheduled[0]
    result = focus.tap(state, early["id"], now, rng)
    assert result["outcome"] == "too_early"
    assert state["score"] == 0 and state["lives"] == 3


def test_opening_warmup_has_shapes_but_no_targets():
    rng = random.Random(7)
    state = focus.new_state("hard", NOW, rng)
    focus.resume(state, NOW)
    # Step in ~poll-sized increments, like the real client.
    for dt in (400, 800, 1_200, 1_600):
        focus.advance(state, NOW + dt, rng)
    early = [o for o in state["objects"] if o["spawned_at_ms"] < NOW + focus.WARMUP_MS]
    assert early, "shapes should already be falling during warm-up"
    assert not any(focus.is_target_object(o) for o in early)


def test_tapping_the_target_scores_once():
    state, rng = _started("easy")
    target = _target(state)
    result = focus.tap(state, target["id"], NOW + focus.WARMUP_MS + 401, rng)
    assert result == {"outcome": "hit", "object_id": target["id"], "points": 11}
    assert state["score"] == 11 and state["hits"] == 1 and state["combo"] == 1
    assert target["id"] not in {o["id"] for o in state["objects"]}

    again = focus.tap(state, target["id"], NOW + focus.WARMUP_MS + 420, rng)
    assert again["outcome"] == "duplicate"
    assert state["score"] == 11  # never pays twice for one object


def test_distractor_tap_costs_no_life_and_no_points():
    state, rng = _started("easy")
    # Force a spawn that is certainly not the target.
    distractor = focus._spawn(state, focus.config_for("easy"), NOW, rng)
    distractor["is_target"] = False
    distractor["color"] = "red" if state["target"]["color"] != "red" else "blue"
    distractor["shape"] = "square" if state["target"]["shape"] != "square" else "circle"
    result = focus.tap(state, distractor["id"], NOW + 50, rng)
    assert result["outcome"] == "wrong"
    assert state["score"] == 0 and state["lives"] == 3
    assert state["wrong_taps"] == 1 and state["combo"] == 0


def test_missed_target_costs_one_life_but_missed_distractor_does_not():
    state, rng = _started("easy")
    cfg = focus.config_for("easy")
    t0 = NOW + focus.WARMUP_MS + 400
    # Controlled scene: one target, no further spawns, so exactly one miss.
    state["objects"] = []
    state["next_spawn_ms"] = NOW + 10**9
    state["next_target_ms"] = NOW + 10**9
    target = focus._spawn(state, cfg, t0, rng, force_target=True)
    target["fall_ms"] = 1_000

    focus.advance(state, t0 + 500, rng)
    assert state["lives"] == 3  # still airborne
    focus.advance(state, t0 + 1_001, rng)
    assert state["lives"] == 2 and state["missed_targets"] == 1

    # A distractor falling out costs nothing at all.
    distractor = focus._spawn(state, cfg, t0 + 1_100, rng)
    distractor["is_target"] = False
    distractor["fall_ms"] = 500
    focus.advance(state, t0 + 1_601, rng)
    assert state["lives"] == 2 and state["missed_targets"] == 1
    assert state["distractors_passed"] >= 1


def test_three_missed_targets_end_the_run():
    state, rng = _started("hard", seed=3)
    t = NOW
    while not state["finished"] and t < NOW + 120_000:
        t += 200
        focus.advance(state, t, rng)
    assert state["finished"] is True
    assert state["lives"] == 0
    assert state["missed_targets"] == 3
    assert state["objects"] == []


def test_target_change_neutralises_in_flight_objects():
    state, rng = _started("easy")
    cfg = focus.config_for("easy")
    t0 = NOW + focus.WARMUP_MS + 400
    old_target = dict(state["target"])
    # Two objects born under the old instruction.
    state["objects"] = []
    tapped_one = focus._spawn(state, cfg, t0, rng, force_target=True)
    falling_one = focus._spawn(state, cfg, t0, rng, force_target=True)
    tapped_one["fall_ms"] = 10_000
    falling_one["fall_ms"] = 1_000

    state["next_target_change_ms"] = t0 + 1
    state["next_target_ms"] = t0 + 1
    focus.advance(state, t0 + 60, rng)

    assert state["target"] != old_target
    assert tapped_one["stale"] is True and falling_one["stale"] is True
    # A stale object cannot award points under the new instruction ...
    score_before = state["score"]
    result = focus.tap(state, tapped_one["id"], t0 + 70, rng)
    assert result["outcome"] == "wrong"
    assert state["score"] == score_before
    # ... and cannot cost a life when it reaches the bottom.
    state["objects"] = [falling_one]  # isolate it from later target spawns
    state["next_spawn_ms"] = NOW + 10**9
    state["next_target_ms"] = NOW + 10**9
    lives_before = state["lives"]
    focus.advance(state, t0 + 1_001, rng)
    assert state["lives"] == lives_before
    assert state["missed_targets"] == 0


def test_pause_freezes_the_clock_and_resume_shifts_the_timeline():
    state, rng = _started("medium")
    in_flight = state["objects"][0]
    spawned_at = in_flight["spawned_at_ms"]

    focus.pause(state, NOW + 100)
    focus.advance(state, NOW + 60_000, rng)
    assert state["lives"] == 3 and state["missed_targets"] == 0
    assert in_flight["spawned_at_ms"] == spawned_at

    paused_for = 60_000 - 100
    focus.resume(state, NOW + 60_000)
    assert state["paused"] is False
    assert in_flight["spawned_at_ms"] == spawned_at + paused_for
    assert state["paused_total_ms"] == paused_for


def test_long_stall_rebases_without_stealing_lives():
    state, rng = _started("medium")
    focus.advance(state, NOW + 20_000, rng)  # backgrounded tab
    assert state["lives"] == 3 and state["missed_targets"] == 0
    # Nothing from the missed window is still on screen; only fresh, still
    # scheduled shapes remain for the resumed client.
    assert all(o["spawned_at_ms"] >= NOW + 19_000 for o in state["objects"])


def test_finish_computes_result_and_xp_server_side():
    state, rng = _started("hard")
    for step in range(120):
        t = NOW + (step + 1) * 100
        focus.advance(state, t, rng)
        for obj in list(state["objects"]):
            if focus.is_target_object(obj):
                focus.tap(state, obj["id"], t, rng)
        if state["finished"]:
            break
    result = focus.finish(state, NOW + 20_000)
    assert result["score"] == state["score"]
    assert result["xp_earned"] >= 1
    assert 0 <= result["accuracy_percent"] <= 100
    assert result["duration_ms"] >= 0
    assert result["outcome"] in {"win", "loss"}
    # Finishing twice is stable (one payout).
    assert focus.finish(state, NOW + 2_000) == result


def test_difficulties_actually_scale():
    easy = focus.config_for("easy")
    medium = focus.config_for("medium")
    hard = focus.config_for("hard")
    assert easy.fall_ms > medium.fall_ms > hard.fall_ms
    assert easy.spawn_interval_ms > medium.spawn_interval_ms > hard.spawn_interval_ms
    assert easy.max_objects < medium.max_objects < hard.max_objects
    assert len(easy.colors) < len(hard.colors)
    assert len(easy.shapes) < len(hard.shapes)
    for cfg in (easy, medium, hard):
        assert focus.MAX_LIVES == 3  # missed-target limit is constant


def test_public_view_is_the_render_contract():
    state, _ = _started("medium")
    view = focus.public_view(state, NOW, session_id="sid")
    assert view["session_id"] == "sid"
    assert view["game_type"] == "focus_rush"
    assert view["target"] == state["target"]
    assert view["instruction"].startswith("TAP ")
    assert view["max_lives"] == 3 and view["lives"] == 3
    assert view["config"]["fall_ms"] == focus.config_for("medium").fall_ms
    assert view["objects"][0].keys() == {
        "id", "color", "shape", "x", "spawned_at_ms", "fall_ms", "stale",
    }
    assert view["now_ms"] == NOW


def test_unknown_difficulty_is_rejected():
    with pytest.raises(ValueError):
        focus.config_for("impossible")


# ---------------------------------------------------------------------------
# Service: server-authoritative scoring and pause
# ---------------------------------------------------------------------------


def _user():
    from brainrush.db.models import User

    user = User(telegram_id=9101, username="focuser", display_name="Focus")
    user.id = uuid.uuid4()
    return user


def _focus_row(user_id, session_id, difficulty="easy", now=NOW, seed=11):
    rng = random.Random(seed)
    data = focus.new_state(difficulty, now, rng)
    focus.resume(data, now)
    focus.advance(data, now + focus.WARMUP_MS + 400, rng)  # past warm-up
    row = WebappGameState(
        user_id=user_id,
        session_id=session_id,
        game_type="focus_rush",
        difficulty=difficulty,
        secret=0,
        max_attempts=focus.MAX_LIVES,
        guesses=data,
    )
    row.id = uuid.uuid4()
    return row


async def test_start_focus_run_returns_paused_public_view():
    user = _user()
    session = RecordingSession(
        script=[FakeResult(rowcount=0), user, FakeResult(rows=[])]
    )
    svc = MiniappGameService(session)
    view = await svc.start_game(
        user_id=user.id, difficulty="medium", game_type="focus_rush"
    )
    assert view["game_type"] == "focus_rush"
    assert view["paused"] is True
    assert view["lives"] == 3 and view["score"] == 0
    assert view["objects"] == []
    assert view["config"]["spawn_interval_ms"] == 780


async def test_focus_tap_scores_server_side_and_dedupes(monkeypatch):
    user = _user()
    sid = uuid.uuid4()
    row = _focus_row(user.id, sid)
    target = _target(row.guesses)
    monkeypatch.setattr(
        "brainrush.services.miniapp._now_ms",
        lambda: NOW + focus.WARMUP_MS + 500,
    )
    session = RecordingSession(script=[FakeResult(rows=[row]), FakeResult(rows=[row])])
    svc = MiniappGameService(session)

    view = await svc.focus_tap(
        session_id=sid, user_id=user.id, object_id=target["id"],
        client_move_id="m1",
    )
    cfg = focus.config_for("easy")
    assert view["score"] == cfg.hit_points + 1
    assert view["hits"] == 1 and view["lives"] == 3
    assert view["last_tap"]["outcome"] == "hit"

    retry = await svc.focus_tap(
        session_id=sid, user_id=user.id, object_id=target["id"],
        client_move_id="m1",
    )
    assert retry["score"] == view["score"]  # idempotent per client_move_id


async def test_focus_tap_on_unknown_object_is_rejected_without_scoring(monkeypatch):
    user = _user()
    sid = uuid.uuid4()
    row = _focus_row(user.id, sid)
    monkeypatch.setattr("brainrush.services.miniapp._now_ms", lambda: NOW + 250)
    session = RecordingSession(script=[FakeResult(rows=[row])])
    svc = MiniappGameService(session)

    view = await svc.focus_tap(
        session_id=sid, user_id=user.id, object_id="not-a-real-object",
        client_move_id="m2",
    )
    assert view["last_tap"]["outcome"] == "expired"
    assert view["score"] == 0 and view["lives"] == 3


async def test_focus_pause_then_resume(monkeypatch):
    user = _user()
    sid = uuid.uuid4()
    row = _focus_row(user.id, sid)
    session = RecordingSession(script=[FakeResult(rows=[row]), FakeResult(rows=[row])])
    svc = MiniappGameService(session)

    monkeypatch.setattr("brainrush.services.miniapp._now_ms", lambda: NOW + 100)
    paused = await svc.focus_pause(session_id=sid, user_id=user.id, paused=True)
    assert paused["paused"] is True

    monkeypatch.setattr("brainrush.services.miniapp._now_ms", lambda: NOW + 10_100)
    resumed = await svc.focus_pause(session_id=sid, user_id=user.id, paused=False)
    assert resumed["paused"] is False
    assert resumed["lives"] == 3
    assert resumed["objects"]  # play resumes with shapes on screen
