"""Bot tests: handlers + session middleware with mocks only.

No real Telegram API calls: messages are fakes recording `answer()` text, and
services are stubbed. No real DB either.
"""
import uuid
from types import SimpleNamespace

import pytest

from brainrush.bot import handlers
from brainrush.bot.factory import create_dispatcher
from brainrush.bot.middleware import DbSessionMiddleware
from brainrush.db.errors import NotFoundError
from brainrush.db.models import PlayerProfile, User


def _tg_user(*, uid=123, username="ada", full_name="Ada L"):
    return SimpleNamespace(id=uid, username=username, full_name=full_name)


def _message(*, user="present", **kw):
    sent = []

    async def answer(text, **kwargs):
        sent.append(text)

    msg = SimpleNamespace(
        from_user=None if user == "absent" else _tg_user(**kw),
        answer=answer,
    )
    msg.sent = sent
    return msg


def _user(uid=123, **kw):
    user = User(telegram_id=uid, **kw)
    user.id = uuid.uuid4()
    return user


def _profile(user_id, **kw):
    defaults = dict(
        total_xp=150, current_level=3, games_played=10,
        wins=6, losses=3, current_streak=2, longest_streak=4,
    )
    defaults.update(kw)
    profile = PlayerProfile(user_id=user_id, **defaults)
    profile.id = uuid.uuid4()
    return profile


class StubUserService:
    last = None

    def __init__(self, session):
        self.session = session
        self.calls = []
        StubUserService.last = self

    async def get_or_register(self, *, telegram_id, username=None, display_name=None):
        self.calls.append((telegram_id, username, display_name))
        user = _user(telegram_id, username=username, display_name=display_name)
        return user, _profile(user.id)


class ExplodingUserService(StubUserService):
    async def get_or_register(self, **kwargs):
        raise RuntimeError("db down")


class StubProfileService:
    def __init__(self, session, profile=None, error=None):
        self.session = session
        self._profile = profile
        self._error = error

    async def get_stats(self, *, user_id):
        if self._error is not None:
            raise self._error
        return self._profile


class _ClosedTracker:
    def __init__(self):
        self.created = []
        self.closed = 0

    def __call__(self):
        tracker = self
        session = SimpleNamespace(marker=object())

        class _CM:
            async def __aenter__(self):
                tracker.created.append(session)
                return session

            async def __aexit__(self, *exc):
                tracker.closed += 1
                return False

        return _CM()


async def test_start_registers_and_welcomes(monkeypatch):
    monkeypatch.setattr(handlers, "UserService", StubUserService)
    msg = _message()
    await handlers.cmd_start(msg, session=object())

    assert len(msg.sent) == 1
    assert "Ada L" in msg.sent[0] and "/profile" in msg.sent[0]
    assert StubUserService.last.calls == [(123, "ada", "Ada L")]


async def test_start_without_username_registers_none(monkeypatch):
    monkeypatch.setattr(handlers, "UserService", StubUserService)
    msg = _message(username=None, full_name="No Nick")
    await handlers.cmd_start(msg, session=object())

    assert StubUserService.last.calls == [(123, None, "No Nick")]
    assert "No Nick" in msg.sent[0]


async def test_start_no_from_user_is_friendly():
    msg = _message(user="absent")
    await handlers.cmd_start(msg, session=object())
    assert len(msg.sent) == 1 and "personal chat" in msg.sent[0]


async def test_start_failure_is_friendly(monkeypatch):
    monkeypatch.setattr(handlers, "UserService", ExplodingUserService)
    msg = _message()
    await handlers.cmd_start(msg, session=object())
    assert msg.sent == ["Something went wrong on our side. Please try again in a moment."]


async def test_help_lists_commands():
    msg = _message()
    await handlers.cmd_help(msg)
    for cmd in ("/start", "/help", "/profile", "/games", "/play", "/leaderboard", "/daily"):
        assert cmd in msg.sent[0]


async def test_profile_shows_saved_stats(monkeypatch):
    user = _user()
    profile = _profile(user.id)
    monkeypatch.setattr(handlers, "UserService", StubUserService)
    monkeypatch.setattr(
        handlers, "ProfileService", lambda session: StubProfileService(session, profile)
    )
    msg = _message()
    await handlers.cmd_profile(msg, session=object())

    text = msg.sent[0]
    for expected in ("Level: 3", "XP: 150", "Games played: 10", "Wins: 6",
                     "Losses: 3", "Current streak: 2", "Longest streak: 4"):
        assert expected in text


async def test_profile_missing_is_friendly(monkeypatch):
    monkeypatch.setattr(handlers, "UserService", StubUserService)
    monkeypatch.setattr(
        handlers, "ProfileService",
        lambda session: StubProfileService(session, error=NotFoundError("gone")),
    )
    msg = _message()
    await handlers.cmd_profile(msg, session=object())
    assert "/start" in msg.sent[0]


async def test_profile_escapes_display_name(monkeypatch):
    monkeypatch.setattr(handlers, "UserService", StubUserService)
    user = _user()
    monkeypatch.setattr(
        handlers, "ProfileService",
        lambda session: StubProfileService(session, _profile(user.id)),
    )
    msg = _message(full_name="<b>evil</b>")
    await handlers.cmd_profile(msg, session=object())
    assert "<b>evil</b>" not in msg.sent[0]
    assert "&lt;b&gt;evil&lt;/b&gt;" in msg.sent[0]


async def test_games_leaderboard_daily_are_honest_placeholders():
    for fn in (handlers.cmd_games,
               handlers.cmd_leaderboard, handlers.cmd_daily):
        msg = _message()
        await fn(msg)
        assert len(msg.sent) == 1
    assert "coming soon" in (await _run(handlers.cmd_games)).lower()
    assert "coming soon" in (await _run(handlers.cmd_leaderboard)).lower()
    assert "coming soon" in (await _run(handlers.cmd_daily)).lower()


async def _run(fn):
    msg = _message()
    await fn(msg)
    return msg.sent[0]


async def test_leaderboard_and_daily_invent_nothing():
    lb = await _run(handlers.cmd_leaderboard)
    daily = await _run(handlers.cmd_daily)
    for invented in ("1.", "#1", "points: 999", "coins"):
        assert invented not in lb and invented not in daily


async def test_middleware_injects_fresh_session_per_update_and_closes():
    tracker = _ClosedTracker()
    middleware = DbSessionMiddleware(tracker)
    seen = []

    async def handler(event, data):
        seen.append(data["session"])
        return "ok"

    assert await middleware(handler, object(), {}) == "ok"
    assert await middleware(handler, object(), {}) == "ok"
    assert len(tracker.created) == 2
    assert seen[0] is not seen[1]
    assert tracker.closed == 2


async def test_middleware_closes_session_on_handler_failure():
    tracker = _ClosedTracker()
    middleware = DbSessionMiddleware(tracker)

    async def failing(event, data):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await middleware(failing, object(), {})
    assert tracker.closed == 1


def test_dispatcher_wires_middleware_and_router():
    from aiogram import Router

    from brainrush.bot.middleware import DbSessionMiddleware

    def _ours(dp):
        return [
            m for m in dp.update.outer_middleware._middlewares
            if isinstance(m, DbSessionMiddleware)
        ]

    tracker = _ClosedTracker()
    dp = create_dispatcher(tracker, router=Router())
    assert dp is not None
    assert len(_ours(dp)) == 1

    plain = create_dispatcher(router=Router())
    assert len(_ours(plain)) == 0


async def test_start_attaches_webapp_button_when_configured(monkeypatch):
    from brainrush.bot import handlers as _h

    monkeypatch.setattr(_h, "UserService", StubUserService)
    _h.configure_webapp("https://app.example.example")
    try:
        answered = []

        async def answer(text, reply_markup=None, **kwargs):
            answered.append((text, reply_markup))

        msg = _message()
        msg.answer = answer
        await _h.cmd_start(msg, session=object())

        text, markup = answered[0]
        assert markup is not None
        button = markup.inline_keyboard[0][0]
        assert button.text == "Open BrainRush"
        assert button.web_app.url == "https://app.example.example"
    finally:
        _h.configure_webapp("")


async def test_start_omits_button_without_url(monkeypatch):
    from brainrush.bot import handlers as _h

    monkeypatch.setattr(_h, "UserService", StubUserService)
    _h.configure_webapp("")
    answered = []

    async def answer(text, reply_markup=None, **kwargs):
        answered.append((text, reply_markup))

    msg = _message()
    msg.answer = answer
    await _h.cmd_start(msg, session=object())
    assert answered[0][1] is None
