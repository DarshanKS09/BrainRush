"""Match room codes + join-by-code: no real DB/Telegram.

Reuses the stub repositories from test_matches. Covers code issuance on
create, successful code joins (both directions), idempotent repeat joins,
unknown/malformed codes, expired/full/finished lobbies, code-vs-token
separation, and the join-by-code route.
"""
import re
import uuid

import pytest

from brainrush.db.errors import ConflictError, NotFoundError
from tests.test_matches import StubMatches as _BaseStubMatches, _registered, _service
from tests.test_repositories import FakeResult, RecordingSession


class StubMatches(_BaseStubMatches):
    """Same in-memory stub plus room-code support under test."""

    async def create(self, **kw):
        from brainrush.db.repository import _new_room_code

        row = await super().create(**kw)
        row.room_code = _new_room_code()
        return row

    async def get_by_room_code(self, *, room_code):
        from brainrush.db.repository import _require_room_code

        code = _require_room_code(room_code)
        for row in self.rows.values():
            if getattr(row, "room_code", None) == code:
                return row
        return None


def _svc():
    return _service(RecordingSession(), matches=StubMatches())


async def _create_lobby(svc, user, *, game_type="number_guessing",
                        mode="duel", room_code="ABC123"):
    view = await svc.create_match(
        host_user_id=user.id, game_type=game_type, mode=mode,
        difficulty="hard",
    )
    match_id = uuid.UUID(view["match_id"])
    svc.matches.rows[match_id].room_code = room_code
    view["room_code"] = room_code
    return match_id, view


async def test_create_issues_human_code_separate_from_token():
    from brainrush.db.repository import _new_room_code, _require_room_code

    svc = _svc()
    user = _registered(svc, 111)
    view = await svc.create_match(
        host_user_id=user.id, game_type="number_guessing", mode="duel",
        difficulty="hard",
    )
    assert re.fullmatch(r"[A-Z0-9]{4,12}", view["room_code"])
    assert view["room_code"] != svc.matches.rows[uuid.UUID(view["match_id"])].invite_token
    assert _require_room_code("  abc123 ") == "ABC123"
    for bad in ("", "ab", "!!!", "x" * 13, None, 123):
        with pytest.raises(ValueError):
            _require_room_code(bad)
    assert re.fullmatch(r"[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{6}", _new_room_code())


async def test_join_by_code_second_user_and_idempotent_repeat():
    svc = _svc()
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    mid, view = await _create_lobby(svc, host, room_code="ABC123")
    assert view["room_code"] == "ABC123"

    joined = await svc.join_by_code(user_id=guest.id, room_code="abc123")
    assert joined["match_id"] == str(mid)
    assert joined["count"] == 2

    again = await svc.join_by_code(user_id=guest.id, room_code="ABC123")
    assert again["count"] == 2  # no duplicate seat
    assert await svc.parts.count_by_match(match_id=mid) == 2


async def test_join_by_code_rejects_unknown_and_malformed():
    svc = _svc()
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    await _create_lobby(svc, host, room_code="ABC123")
    with pytest.raises(NotFoundError, match="Room not found"):
        await svc.join_by_code(user_id=guest.id, room_code="ZZZ999")
    with pytest.raises(ValueError):
        await svc.join_by_code(user_id=guest.id, room_code="!!!")


async def test_join_by_code_rejects_full_finished_expired():
    svc = _svc()
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    other = _registered(svc, 333)
    mid, _ = await _create_lobby(svc, host, room_code="ABC123")  # duel, max 2
    await svc.join_by_code(user_id=guest.id, room_code="ABC123")
    with pytest.raises(ConflictError, match="full"):
        await svc.join_by_code(user_id=other.id, room_code="ABC123")

    # Completed matches are finished, not joinable.
    svc.matches.rows[mid].status = "completed"
    with pytest.raises(ConflictError, match="already finished"):
        await svc.join_by_code(user_id=other.id, room_code="ABC123")

    # Expired lobbies report expiry, not a generic finish.
    svc.matches.rows[mid].status = "lobby"
    import datetime

    svc.matches.rows[mid].created_at = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=49)
    )
    with pytest.raises(ConflictError, match="expired"):
        await svc.join_by_code(user_id=other.id, room_code="ABC123")


async def test_token_is_not_a_code_and_code_is_not_a_token():
    svc = _svc()
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    mid, view = await _create_lobby(svc, host, room_code="ABC123")
    token = svc.matches.rows[mid].invite_token
    assert token.startswith("m-")
    # Room code rejected where a token is required.
    with pytest.raises(NotFoundError):
        await svc.join_by_token(user_id=guest.id, token="ABC123")
    # Token rejected where a code is required (wrong shape for codes).
    with pytest.raises((NotFoundError, ValueError)):
        await svc.join_by_code(user_id=guest.id, room_code=token)


async def test_concurrent_code_joins_single_seat():
    import asyncio

    svc = _svc()
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    await _create_lobby(svc, host, room_code="ABC123")
    results = await asyncio.gather(
        svc.join_by_code(user_id=guest.id, room_code="ABC123"),
        svc.join_by_code(user_id=guest.id, room_code="ABC123"),
        return_exceptions=True,
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    mid = next(iter(svc.matches.rows))
    assert await svc.parts.count_by_match(match_id=mid) == 2


def test_join_by_code_route(monkeypatch):
    from fastapi import Request
    from fastapi.testclient import TestClient

    from brainrush.api import routes
    from brainrush.api.app import create_app
    from brainrush.api.deps import get_session, get_verified_identity
    from brainrush.config import Settings

    seen = {}

    class StubService:
        def __init__(self, session, **kwargs):
            pass

        async def join_by_code(self, *, user_id, room_code):
            seen["args"] = (user_id, room_code)
            return {"match_id": "m1", "room_code": room_code}

    app = create_app(
        Settings(BOT_TOKEN="test-token",
                 DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db"),
        session_factory=lambda: _DummyCM(),
    )

    async def fake_session(request: Request):
        yield object()

    async def fake_identity(request: Request):
        return {"user_id": uuid.uuid4(), "telegram_id": 1,
                "username": "u", "display_name": "U"}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_verified_identity] = fake_identity
    monkeypatch.setattr(routes, "MatchService", StubService)
    client = TestClient(app, raise_server_exceptions=False)

    ok = client.post("/api/matches/join-by-code",
                     headers={"X-Telegram-Init-Data": "x"},
                     json={"code": "ABC123"})
    assert ok.status_code == 200
    assert seen["args"][1] == "ABC123"
    assert ok.json()["room_code"] == "ABC123"

    assert client.post("/api/matches/join-by-code",
                       headers={"X-Telegram-Init-Data": "x"},
                       json={"code": ""}).status_code == 422


def test_two_participant_room_lifecycle_over_http(monkeypatch):
    """End-to-end room flow with two authenticated identities: host creates
    (persistent room + code), guest joins by code, lobby shows both, host
    starts, repeat joins stay idempotent, strangers cannot start."""
    from fastapi import Request
    from fastapi.testclient import TestClient

    from brainrush.api import routes
    from brainrush.api.app import create_app
    from brainrush.api.deps import get_session, get_verified_identity
    from brainrush.config import Settings
    from tests.test_matches import (
        StubActivities,
        StubInvites,
        StubParts,
        StubProfiles,
        StubResults,
        StubRewards,
        StubSessions,
        StubStates,
        StubUsers,
    )

    users, profiles = StubUsers(), StubProfiles()
    state = {
        "users": users, "profiles": profiles,
        "sessions": StubSessions(), "results": StubResults(),
        "activities": StubActivities(), "matches": StubMatches(),
        "parts": StubParts(), "invites": StubInvites(),
        "rewards": StubRewards(), "states": StubStates(),
    }

    from brainrush.services import matches as matches_module

    class WiredService(matches_module.MatchService):
        def __init__(self, session, **kwargs):
            super().__init__(
                session, completion_xp=10, win_bonus=10, daily_cap=500,
                lobby_ttl_hours=24, invite_ttl_days=7, default_minutes=60,
            )
            for key, repo in state.items():
                setattr(self, key, repo)

    tags = {}

    def _user_for(tag, telegram_id):
        if tag not in tags:
            user = users.add(telegram_id, username=tag, display_name=f"Player {tag}")
            profiles.ensure(user.id)
            tags[tag] = user
        return tags[tag]

    app = create_app(
        Settings(BOT_TOKEN="test-token",
                 DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db"),
        session_factory=lambda: _DummyCM(),
    )

    async def fake_session(request: Request):
        from tests.test_repositories import RecordingSession as RS
        yield RS()

    async def fake_identity(request: Request):
        tag = request.headers.get("x-test-user", "host")
        tid = {"host": 111, "guest": 222, "stranger": 333}[tag]
        user = _user_for(tag, tid)
        return {"user_id": user.id, "telegram_id": tid,
                "username": tag, "display_name": f"Player {tag}"}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_verified_identity] = fake_identity
    monkeypatch.setattr(routes, "MatchService", WiredService)
    client = TestClient(app, raise_server_exceptions=False)

    def headers(tag):
        return {"X-Telegram-Init-Data": "x", "X-Test-User": tag}

    created = client.post("/api/matches", headers=headers("host"),
                          json={"game_type": "number_guessing",
                                "mode": "duel", "difficulty": "hard"})
    assert created.status_code == 200
    body = created.json()
    assert re.fullmatch(r"[A-Z0-9]{4,12}", body["room_code"])
    mid, code = body["match_id"], body["room_code"]

    joined = client.post("/api/matches/join-by-code", headers=headers("guest"),
                         json={"code": code.lower()})  # lowercase accepted
    assert joined.status_code == 200
    assert joined.json()["count"] == 2

    lobby = client.get(f"/api/matches/{mid}", headers=headers("guest"))
    assert lobby.status_code == 200
    assert lobby.json()["count"] == 2
    assert lobby.json()["room_code"] == code

    # Stranger (authenticated but not host/participant) cannot start.
    denied = client.post(f"/api/matches/{mid}/start", headers=headers("stranger"))
    assert denied.status_code in (404, 409)

    started = client.post(f"/api/matches/{mid}/start", headers=headers("host"))
    assert started.status_code == 200
    assert started.json()["status"] == "active"

    # Late repeat join on an active match stays idempotent, no dup seat.
    again = client.post("/api/matches/join-by-code", headers=headers("guest"),
                        json={"code": code})
    assert again.status_code == 200
    assert again.json()["count"] == 2


class _DummyCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False
