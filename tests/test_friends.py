"""Friend codes + friendships: service + route tests. No real DB/Telegram.

Covers stable codes, successful adds, already-friends idempotency, self /
invalid / unknown rejection, duplicate + concurrent safety, symmetric lists,
auth mapping, and the key invariant: friendships never grant referral XP.
"""
import re
import uuid
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from brainrush.api import routes
from brainrush.api.app import create_app
from brainrush.api.deps import get_session, get_verified_identity
from brainrush.config import Settings
from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.models import PlayerProfile, User
from brainrush.services.friends import FriendService
from tests.test_repositories import RecordingSession


# -- stubs -----------------------------------------------------------------

class StubUsers:
    def __init__(self):
        self.by_id = {}

    def add(self, telegram_id, username=None, display_name=None):
        user = User(telegram_id=telegram_id, username=username, display_name=display_name)
        user.id = uuid.uuid4()
        self.by_id[user.id] = user
        return user

    async def get_by_id(self, uid):
        return self.by_id.get(uid)

    async def list_by_ids(self, ids):
        return [self.by_id[i] for i in ids if i in self.by_id]


class StubProfiles:
    def __init__(self):
        self.by_user = {}
        self.xp_calls = []

    def ensure(self, user_id, total_xp=0):
        profile = PlayerProfile(
            user_id=user_id, total_xp=total_xp, current_level=1, games_played=0,
            wins=0, losses=0, current_streak=0, longest_streak=0,
        )
        profile.id = uuid.uuid4()
        self.by_user[user_id] = profile
        return profile

    async def get_by_user_id(self, uid):
        return self.by_user.get(uid)

    async def list_by_user_ids(self, ids):
        return [self.by_user[i] for i in ids if i in self.by_user]

    async def add_xp(self, *, user_id, amount):  # pragma: no cover - must stay unused
        self.xp_calls.append((user_id, amount))
        raise AssertionError("friendship must never award XP")


class StubFriends:
    def __init__(self, raise_on_record=None):
        self.codes = {}
        self.by_user = {}
        self.pairs = set()  # canonical (low, high) uuid pairs
        self.raise_on_record = raise_on_record

    @staticmethod
    def _canon(a, b):
        return (a, b) if a.bytes < b.bytes else (b, a)

    async def get_or_create_code(self, *, user_id):
        if user_id in self.by_user:
            return SimpleNamespace(code=self.by_user[user_id], user_id=user_id), False
        code = f"F{len(self.codes):09d}"
        self.codes[code] = user_id
        self.by_user[user_id] = code
        return SimpleNamespace(code=code, user_id=user_id), True

    async def get_by_code(self, *, code):
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9]{4,32}", code.strip()):
            raise ValueError("invalid friend code")
        if code in self.codes:
            return SimpleNamespace(code=code, user_id=self.codes[code])
        return None

    async def get_pair(self, a, b):
        low, high = self._canon(a, b)
        if (low, high) in self.pairs:
            return SimpleNamespace(user_low=low, user_high=high)
        return None

    async def record_pair(self, a, b):
        if self.raise_on_record is not None:
            raise self.raise_on_record
        low, high = self._canon(a, b)
        if low == high:
            raise ValueError("cannot befriend yourself")
        if (low, high) in self.pairs:
            raise IntegrityError("INSERT", {}, Exception("uq"))
        self.pairs.add((low, high))
        return SimpleNamespace(user_low=low, user_high=high)

    async def list_pairs(self, *, user_id):
        out = []
        for low, high in sorted(self.pairs):
            if low == user_id or high == user_id:
                out.append(SimpleNamespace(user_low=low, user_high=high))
        return out


def _service(session, users=None, profiles=None, friends=None):
    svc = FriendService(session)
    svc.users = users or StubUsers()
    svc.profiles = profiles or StubProfiles()
    svc.friends = friends or StubFriends()
    return svc


def _registered(svc, telegram_id, **kw):
    user = svc.users.add(telegram_id, **kw)
    svc.profiles.ensure(user.id)
    return user


# -- service -----------------------------------------------------------------

async def test_code_stable_per_user():
    session = RecordingSession()
    svc = _service(session)
    user = _registered(svc, 111)
    first = await svc.my_code(user_id=user.id)
    second = await svc.my_code(user_id=user.id)
    assert first["code"] == second["code"]
    assert re.fullmatch(r"[A-Za-z0-9]{4,32}", first["code"])
    assert session.commits == 0


async def test_add_friend_success_between_registered_users():
    session = RecordingSession()
    svc = _service(session)
    alice = _registered(svc, 111, display_name="Alice")
    bob = _registered(svc, 222, display_name="Bob")
    code = (await svc.my_code(user_id=bob.id))["code"]

    out = await svc.add_friend(user_id=alice.id, code=code)

    assert out == {
        "added": True, "already": False,
        "friend": {"display_name": "Bob", "username": bob.username,
                   "level": 1, "total_xp": 0},
    }
    assert svc.profiles.xp_calls == []  # no XP anywhere
    assert session.commits == 0


async def test_add_again_is_idempotent_no_dupes_no_xp():
    session = RecordingSession()
    svc = _service(session)
    alice = _registered(svc, 111)
    bob = _registered(svc, 222)
    code = (await svc.my_code(user_id=bob.id))["code"]

    first = await svc.add_friend(user_id=alice.id, code=code)
    second = await svc.add_friend(user_id=alice.id, code=code)
    third = await svc.add_friend(user_id=bob.id, code=(await svc.my_code(user_id=alice.id))["code"])

    assert first["added"] is True
    assert second == {**second, "added": False, "already": True}
    assert third["already"] is True  # reverse direction collapses too
    assert len(svc.friends.pairs) == 1
    assert svc.profiles.xp_calls == []


async def test_self_add_rejected():
    session = RecordingSession()
    svc = _service(session)
    me = _registered(svc, 111)
    code = (await svc.my_code(user_id=me.id))["code"]
    with pytest.raises(ConflictError, match="yourself"):
        await svc.add_friend(user_id=me.id, code=code)
    assert svc.friends.pairs == set()


async def test_unknown_and_malformed_codes_rejected():
    session = RecordingSession()
    svc = _service(session)
    alice = _registered(svc, 111)
    with pytest.raises(NotFoundError, match="not found"):
        await svc.add_friend(user_id=alice.id, code="ZZZZ9999ZZ")
    with pytest.raises(ValueError):
        await svc.add_friend(user_id=alice.id, code="!!!")
    with pytest.raises(NotFoundError):
        await svc.my_code(user_id=uuid.uuid4())


async def test_concurrent_adds_yield_single_row():
    import asyncio

    session = RecordingSession()
    svc = _service(session)
    alice = _registered(svc, 111)
    bob = _registered(svc, 222)
    code = (await svc.my_code(user_id=bob.id))["code"]

    results = await asyncio.gather(
        svc.add_friend(user_id=alice.id, code=code),
        svc.add_friend(user_id=alice.id, code=code),
        return_exceptions=True,
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    assert len(svc.friends.pairs) == 1
    assert svc.profiles.xp_calls == []


async def test_integrity_error_maps_to_idempotent_already():
    session = RecordingSession()
    friends = StubFriends(raise_on_record=IntegrityError("INSERT", {}, Exception("uq")))
    svc = _service(session, friends=friends)
    alice = _registered(svc, 111)
    bob = _registered(svc, 222)
    code = (await svc.my_code(user_id=bob.id))["code"]
    # Simulate the row appearing via the concurrent winner first.
    friends.raise_on_record = None
    friends.pairs.add(StubFriends._canon(alice.id, bob.id))
    friends.raise_on_record = IntegrityError("INSERT", {}, Exception("uq"))
    out = await svc.add_friend(user_id=alice.id, code=code)
    assert out["added"] is False and out["already"] is True


async def test_both_users_see_each_other():
    session = RecordingSession()
    svc = _service(session)
    alice = _registered(svc, 111, display_name="Alice")
    bob = _registered(svc, 222, display_name="Bob")
    carol = _registered(svc, 333, display_name="Carol")
    await svc.add_friend(user_id=alice.id, code=(await svc.my_code(user_id=bob.id))["code"])
    await svc.add_friend(user_id=carol.id, code=(await svc.my_code(user_id=alice.id))["code"])

    alice_friends = await svc.list_friends(user_id=alice.id)
    bob_friends = await svc.list_friends(user_id=bob.id)

    assert {f["display_name"] for f in alice_friends} == {"Bob", "Carol"}
    assert [f["display_name"] for f in bob_friends] == ["Alice"]
    for f in alice_friends + bob_friends:
        assert set(f) == {"display_name", "username", "level", "total_xp"}
        assert "telegram_id" not in f


async def test_list_empty_and_unknown_user():
    session = RecordingSession()
    svc = _service(session)
    alice = _registered(svc, 111)
    assert await svc.list_friends(user_id=alice.id) == []
    with pytest.raises(NotFoundError):
        await svc.list_friends(user_id=uuid.uuid4())


# -- routes --------------------------------------------------------------------

def _settings(**kw):
    base = dict(
        BOT_TOKEN="test-token",
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db",
    )
    base.update(kw)
    return Settings(**base)


class _DummyCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


def _client(monkeypatch):
    from brainrush.services import friends as friends_module

    users, profiles, friends = StubUsers(), StubProfiles(), StubFriends()

    class WiredService(friends_module.FriendService):
        def __init__(self, session, **kwargs):
            super().__init__(session)
            self.users = users
            self.profiles = profiles
            self.friends = friends

    app = create_app(_settings(), session_factory=lambda: _DummyCM())

    async def fake_session(request: Request):
        from tests.test_repositories import RecordingSession as RS
        yield RS()

    async def _register_shared(telegram_id, username, display_name):
        if telegram_id not in [u.telegram_id for u in users.by_id.values()]:
            user = users.add(telegram_id, username=username, display_name=display_name)
            profiles.ensure(user.id)
        else:
            user = next(u for u in users.by_id.values() if u.telegram_id == telegram_id)
        return user

    async def fake_identity(request: Request):
        user = await _register_shared(777, "carol", "Carol D")
        request.state.telegram_id = 777
        return {"user_id": user.id, "telegram_id": 777,
                "username": "carol", "display_name": "Carol D"}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_verified_identity] = fake_identity
    monkeypatch.setattr(routes, "FriendService", WiredService)
    client = TestClient(app, raise_server_exceptions=False)
    return client, users, profiles, friends


def test_friend_routes_end_to_end(monkeypatch):
    client, users, profiles, friends = _client(monkeypatch)
    headers = {"X-Telegram-Init-Data": "anything"}

    mine = client.get("/api/friends/mine", headers=headers)
    assert mine.status_code == 200
    assert re.fullmatch(r"[A-Za-z0-9]{4,32}", mine.json()["code"])

    assert client.get("/api/friends", headers=headers).json() == {"friends": []}

    # Register Bob through the API identity of 778? Identities are stubbed,
    # so create Bob directly and add via his code.
    bob = users.add(778, username="bob", display_name="Bob B")
    profiles.ensure(bob.id)
    bob_code = "BOBCODE99"
    friends.codes[bob_code] = bob.id

    added = client.post("/api/friends/add", headers=headers, json={"code": bob_code})
    assert added.status_code == 200
    assert added.json()["added"] is True

    again = client.post("/api/friends/add", headers=headers, json={"code": bob_code})
    assert again.status_code == 200
    assert again.json()["already"] is True

    listed = client.get("/api/friends", headers=headers).json()["friends"]
    assert [f["display_name"] for f in listed] == ["Bob B"]
    assert "telegram_id" not in listed[0]

    # Friendship grants no XP to anyone.
    assert profiles.xp_calls == []


def test_friend_add_rejects_self_unknown_and_bad_input(monkeypatch):
    client, *_ = _client(monkeypatch)
    headers = {"X-Telegram-Init-Data": "x"}

    mine = client.get("/api/friends/mine", headers=headers).json()["code"]
    assert client.post("/api/friends/add", headers=headers, json={"code": mine}).status_code == 409
    assert client.post("/api/friends/add", headers=headers,
                       json={"code": "NOPE123456"}).status_code == 404
    assert client.post("/api/friends/add", headers=headers, json={"code": ""}).status_code == 422


def test_friend_routes_require_auth(monkeypatch):
    from brainrush.api.deps import get_session as _gs

    app = create_app(_settings(), session_factory=lambda: _DummyCM())

    async def fake_session(request: Request):
        from tests.test_repositories import RecordingSession as RS
        yield RS()

    app.dependency_overrides[_gs] = fake_session
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/friends/mine").status_code in (401, 422)
    assert client.get("/api/friends").status_code in (401, 422)
    assert client.post("/api/friends/add", json={"code": "ABC123"}).status_code in (401, 422)
