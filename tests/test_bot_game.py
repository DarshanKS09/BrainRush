"""Game handler flows with stubbed services. No real Telegram or DB calls."""
import uuid
from types import SimpleNamespace

import pytest

from brainrush.bot import handlers
from brainrush.db.errors import ConflictError
from brainrush.db.models import PlayerProfile, User
from brainrush.game import number_guessing as guessing
from brainrush.game.store import ActiveGame, ActiveGameStore


def _tg_user(*, uid=123, username="ada", full_name="Ada L"):
    return SimpleNamespace(id=uid, username=username, full_name=full_name)


def _message(*, text="hello", uid=123, username="ada", full_name="Ada L"):
    sent = []

    async def answer(body, **kwargs):
        sent.append(body)

    msg = SimpleNamespace(
        from_user=_tg_user(uid=uid, username=username, full_name=full_name),
        text=text,
        answer=answer,
    )
    msg.sent = sent
    return msg


class StubUserService:
    def __init__(self, session):
        self.calls = []

    async def get_or_register(self, *, telegram_id, username=None, display_name=None):
        self.calls.append((telegram_id, username, display_name))
        # Stable id per Telegram user: handlers build one service instance per
        # call, so the id must not depend on instance state.
        user = User(telegram_id=telegram_id, username=username,
                    display_name=display_name)
        user.id = uuid.uuid5(uuid.NAMESPACE_OID, f"tg:{telegram_id}")
        return user, None


class StubGameService:
    """Mimics GameSessionService persistence surface used by handlers."""

    def __init__(self, session, stale=None):
        self.starts = []
        self.finishes = []
        self.abandons = []
        self._finished = set()
        self._stale = list(stale or [])
        self.fail_finish_times = 0
        self.stale_calls = []

    async def abandon_stale_sessions(self, *, user_id):
        self.stale_calls.append(user_id)
        abandoned = list(self._stale)
        self._stale = []
        self.abandons.extend(r.id for r in abandoned)
        return abandoned

    async def start_session(self, *, user_id, game_type):
        row = SimpleNamespace(id=uuid.uuid4(), user_id=user_id, status="started")
        self.starts.append(row)
        return row

    async def finish_session(self, *, session_id, outcome, score, xp_earned,
                             metadata=None, new_level=None, played_at=None):
        if session_id in self._finished:
            raise ConflictError("already finished")
        if self.fail_finish_times > 0:
            self.fail_finish_times -= 1
            raise RuntimeError("db down")
        self._finished.add(session_id)
        self.finishes.append(
            dict(session_id=session_id, outcome=outcome, score=score,
                 xp_earned=xp_earned, metadata=metadata)
        )
        return (None, None, None, None)

    async def abandon_session(self, *, session_id, played_at=None):
        self.abandons.append(session_id)
        return SimpleNamespace(id=session_id, status="abandoned")


def _wire(monkeypatch, game_service=None, secret=42):
    monkeypatch.setattr(handlers, "UserService", StubUserService)
    svc = game_service or StubGameService(session=None)
    monkeypatch.setattr(handlers, "GameSessionService", lambda session: svc)
    monkeypatch.setattr(handlers.guessing, "roll_secret", lambda *a, **k: secret)
    monkeypatch.setattr(handlers, "store", ActiveGameStore())
    # Hermetic fallback path: the Mini App routing tests set their own URL.
    monkeypatch.setattr(handlers, "WEBAPP_URL", "")
    return svc


async def _play(monkeypatch, svc=None, secret=42, **kw):
    svc = _wire(monkeypatch, svc, secret)
    msg = _message(text="/play", **kw)
    await handlers.cmd_play(msg, session=object())
    return msg, svc


async def test_play_starts_game(monkeypatch):
    msg, svc = await _play(monkeypatch)
    assert "1 to 100" in msg.sent[0] and "7 guesses" in msg.sent[0]
    assert len(svc.starts) == 1
    assert len(handlers.store) == 1


async def test_play_twice_keeps_single_game(monkeypatch):
    msg, svc = await _play(monkeypatch)
    msg2 = _message(text="/play")
    await handlers.cmd_play(msg2, session=object())
    assert "already playing" in msg2.sent[0]
    assert len(svc.starts) == 1


async def test_guesses_high_low_without_consuming_on_invalid(monkeypatch):
    await _play(monkeypatch)
    for text, expect in (("50", "Too high"), ("30", "Too low")):
        msg = _message(text=text)
        await handlers.on_guess(msg, session=object())
        assert expect in msg.sent[0] and "left" in msg.sent[0]

    active = next(iter(handlers.store._games.values()))
    assert active.game.attempts_used == 2

    for bad in ("abc", "150", "   "):
        msg = _message(text=bad)
        await handlers.on_guess(msg, session=object())
        assert "guess" in msg.sent[0].lower() or "number" in msg.sent[0].lower()
    assert active.game.attempts_used == 2


async def test_command_text_never_reaches_game(monkeypatch):
    await _play(monkeypatch)
    msg = _message(text="/profile")
    await handlers.on_guess(msg, session=object())
    assert msg.sent == []


async def test_win_flow_persists_once(monkeypatch):
    msg, svc = await _play(monkeypatch)
    for text in ("50", "30"):
        await handlers.on_guess(_message(text=text), session=object())
    win = _message(text="42")
    await handlers.on_guess(win, session=object())

    assert "got it in 3" in win.sent[0] and "+50 XP" in win.sent[0]
    assert len(svc.finishes) == 1
    fin = svc.finishes[0]
    assert fin["outcome"] == "win" and fin["score"] == 3 and fin["xp_earned"] == 50
    assert fin["metadata"]["secret"] == 42
    assert fin["metadata"]["guesses"] == [50, 30, 42]
    assert len(handlers.store) == 0


async def test_loss_flow_reveals_and_awards_consolation(monkeypatch):
    msg, svc = await _play(monkeypatch, secret=99)
    last = None
    for guess in ("1", "2", "3", "4", "5", "6"):
        await handlers.on_guess(_message(text=guess), session=object())
    last = _message(text="7")
    await handlers.on_guess(last, session=object())

    assert "99" in last.sent[0] and "+5 XP" in last.sent[0]
    assert svc.finishes[0]["outcome"] == "loss"
    assert svc.finishes[0]["score"] == 7
    assert len(handlers.store) == 0


async def test_guess_after_completion_records_nothing_more(monkeypatch):
    await _play(monkeypatch)
    await handlers.on_guess(_message(text="42"), session=object())
    again = _message(text="42")
    await handlers.on_guess(again, session=object())
    assert "active game" in again.sent[0] or "ended" in again.sent[0]


async def test_duplicate_finish_is_single_result(monkeypatch):
    msg, svc = await _play(monkeypatch)
    await handlers.on_guess(_message(text="42"), session=object())
    assert len(svc.finishes) == 1
    # simulate the same terminal guess arriving again before cleanup
    active = ActiveGame(
        user_id=next(iter(svc.starts)).user_id,
        session_id=svc.starts[0].id,
        game_type="number_guessing",
        game=guessing.NumberGuessingGame(secret=42),
    )
    handlers.store.put(active)
    dup = _message(text="42")
    await handlers.on_guess(dup, session=object())
    assert len(svc.finishes) == 1
    assert "already recorded" in dup.sent[0]


async def test_users_are_isolated(monkeypatch):
    await _play(monkeypatch, secret=42)
    other = _message(text="10", uid=999, username="bob", full_name="Bob")
    await handlers.on_guess(other, session=object())
    assert "active game" in other.sent[0]
    assert len(handlers.store) == 1


async def test_cancel_abandons_without_xp_or_result(monkeypatch):
    msg, svc = await _play(monkeypatch)
    cancel = _message(text="/cancel")
    await handlers.cmd_cancel(cancel, session=object())

    assert "cancelled" in cancel.sent[0].lower() and "no XP" in cancel.sent[0]
    assert svc.abandons == [svc.starts[0].id]
    assert svc.finishes == []
    assert len(handlers.store) == 0


async def test_cancel_without_game_is_friendly(monkeypatch):
    _wire(monkeypatch)
    msg = _message(text="/cancel")
    await handlers.cmd_cancel(msg, session=object())
    assert "active game" in msg.sent[0]


async def test_failed_save_keeps_guess_retryable(monkeypatch):
    msg, svc = await _play(monkeypatch)
    svc.fail_finish_times = 1
    retry = _message(text="42")
    await handlers.on_guess(retry, session=object())
    assert "again" in retry.sent[0]
    assert svc.finishes == []

    active = next(iter(handlers.store._games.values()))
    assert active.game.attempts_used == 0  # failed save consumed nothing

    win = _message(text="42")
    await handlers.on_guess(win, session=object())
    assert "got it" in win.sent[0]
    assert len(svc.finishes) == 1


async def test_stale_db_session_abandoned_on_play(monkeypatch):
    stale_row = SimpleNamespace(id=uuid.uuid4())
    svc = StubGameService(session=None, stale=[stale_row])
    msg, svc = await _play(monkeypatch, svc=svc)
    assert svc.abandons == [stale_row.id]
    assert len(svc.starts) == 1


async def test_handler_db_failure_is_friendly(monkeypatch):
    class ExplodingUsers(StubUserService):
        async def get_or_register(self, **kwargs):
            raise RuntimeError("db down")

    monkeypatch.setattr(handlers, "UserService", ExplodingUsers)
    monkeypatch.setattr(handlers, "store", ActiveGameStore())
    for fn, kwargs in (
        (handlers.cmd_play, {}),
        (handlers.cmd_cancel, {}),
        (handlers.on_guess, {}),
    ):
        msg = _message(text="/play" if fn is handlers.cmd_play else "5")
        await fn(msg, session=object())
        assert "went wrong" in msg.sent[0]


async def test_play_fallback_without_url(monkeypatch):
    # _wire forces WEBAPP_URL="": legacy text game must still start.
    msg, svc = await _play(monkeypatch)
    assert "guesses" in msg.sent[0]
    assert len(svc.starts) == 1 and len(handlers.store) == 1


def _rich_message(**kw):
    captured = {}

    async def answer(text, reply_markup=None, **kwargs):
        captured["text"] = text
        captured["markup"] = reply_markup

    msg = _message(text="/play", **kw)
    msg.answer = answer
    return msg, captured


async def test_play_routes_to_miniapp_when_configured(monkeypatch):
    svc = _wire(monkeypatch)
    monkeypatch.setattr(handlers, "WEBAPP_URL", "https://app.example.example")
    secrets = []

    def counting_secret(*args, **kwargs):
        secrets.append(True)
        return 42

    monkeypatch.setattr(handlers.guessing, "roll_secret", counting_secret)
    msg, captured = _rich_message()
    await handlers.cmd_play(msg, session=object())

    assert "Mini App" in captured["text"]
    button = captured["markup"].inline_keyboard[0][0]
    assert button.text == "▶ Play in Mini App"
    assert button.web_app.url == "https://app.example.example"
    # No text game may start: no DB session, no abandon sweep, no store
    # entry, and no secret may be generated.
    assert svc.starts == [] and svc.abandons == []
    assert len(handlers.store) == 0
    assert secrets == []
