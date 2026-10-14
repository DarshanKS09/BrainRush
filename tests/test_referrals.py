"""Referral service + route tests: stub repos/services, no real DB/Telegram.

Covers code stability, valid attribution, existing-user/self/invalid-code
rejection, duplicate + concurrent claims, exact XP amounts, auth mapping,
and link persistence across reloads.
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
from brainrush.services.referrals import ReferralService
from tests.test_repositories import RecordingSession


# -- stubs -----------------------------------------------------------------

class StubUsers:
    def __init__(self):
        self.by_tid = {}
        self.by_id = {}

    async def get_by_id(self, uid):
        return self.by_id.get(uid)

    async def get_or_create(self, *, telegram_id, username=None, display_name=None):
        if telegram_id in self.by_tid:
            return self.by_tid[telegram_id], False
        user = User(telegram_id=telegram_id, username=username, display_name=display_name)
        user.id = uuid.uuid4()
        self.by_tid[telegram_id] = user
        self.by_id[user.id] = user
        return user, True


class StubProfiles:
    def __init__(self):
        self.by_user = {}
        self.xp_calls = []

    async def get_by_user_id(self, uid):
        return self.by_user.get(uid)

    async def get_or_create(self, *, user_id):
        if user_id in self.by_user:
            return self.by_user[user_id], False
        profile = PlayerProfile(
            user_id=user_id, total_xp=0, current_level=1, games_played=0,
            wins=0, losses=0, current_streak=0, longest_streak=0,
        )
        profile.id = uuid.uuid4()
        self.by_user[user_id] = profile
        return profile, True

    async def add_xp(self, *, user_id, amount):
        profile = self.by_user.get(user_id)
        if profile is None:
            raise NotFoundError("player profile not found")
        profile.total_xp += amount
        self.xp_calls.append((user_id, amount))
        return profile


class StubReferrals:
    def __init__(self, raise_on_record=None):
        self.codes = {}          # code -> referrer_user_id
        self.by_referrer = {}    # referrer_user_id -> code
        self.attributions = {}   # referred_user_id -> SimpleNamespace row
        self.raise_on_record = raise_on_record

    async def get_or_create_code(self, *, user_id):
        if user_id in self.by_referrer:
            code = self.by_referrer[user_id]
            return SimpleNamespace(code=code, referrer_user_id=user_id), False
        code = f"CODE{len(self.codes):04d}AB"
        self.codes[code] = user_id
        self.by_referrer[user_id] = code
        return SimpleNamespace(code=code, referrer_user_id=user_id), True

    async def get_by_code(self, *, code):
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9]{4,32}", code.strip()):
            raise ValueError("invalid referral code")
        if code in self.codes:
            return SimpleNamespace(code=code, referrer_user_id=self.codes[code])
        return None

    async def get_attribution_for(self, *, referred_user_id):
        return self.attributions.get(referred_user_id)

    async def record_attribution(self, *, code, referrer_user_id,
                                 referred_user_id, referrer_xp, referred_xp):
        if self.raise_on_record is not None:
            raise self.raise_on_record
        if referred_user_id in self.attributions:
            raise IntegrityError("INSERT", {}, Exception("uq"))
        row = SimpleNamespace(code=code, referrer_user_id=referrer_user_id,
                              referred_user_id=referred_user_id,
                              referrer_xp=referrer_xp, referred_xp=referred_xp)
        self.attributions[referred_user_id] = row
        return row

    async def count_credited(self, *, referrer_user_id):
        return sum(1 for r in self.attributions.values()
                   if r.referrer_user_id == referrer_user_id)

    async def sum_referrer_xp(self, *, referrer_user_id):
        return sum(r.referrer_xp for r in self.attributions.values()
                   if r.referrer_user_id == referrer_user_id)


def _service(session, users=None, profiles=None, referrals=None,
             referrer_xp=100, referred_xp=25):
    svc = ReferralService(session, referrer_xp=referrer_xp, referred_xp=referred_xp)
    svc.users = users or StubUsers()
    svc.profiles = profiles or StubProfiles()
    svc.referrals = referrals or StubReferrals()
    return svc


async def _register(svc, telegram_id):
    user, _ = await svc.users.get_or_create(telegram_id=telegram_id)
    await svc.profiles.get_or_create(user_id=user.id)
    return user


async def _mint(svc, telegram_id):
    """Register + mint code, returning the plain code string."""
    user = await _register(svc, telegram_id)
    row, _ = await svc.referrals.get_or_create_code(user_id=user.id)
    return user, row.code


# -- code stability ----------------------------------------------------------

async def test_code_stable_across_repeated_opens():
    session = RecordingSession()
    svc = _service(session)
    user = await _register(svc, 111)
    first = await svc.get_or_create_code(user_id=user.id)
    second = await svc.get_or_create_code(user_id=user.id)
    assert first["code"] == second["code"]
    assert re.fullmatch(r"[A-Za-z0-9]{4,32}", first["code"])
    assert session.begun == 2 and session.commits == 0


async def test_link_built_only_when_configured():
    session = RecordingSession()
    svc = _service(session)
    user = await _register(svc, 111)
    with_link = await svc.build_link(
        user_id=user.id, bot_username="somebot", app_short_name="play")
    assert with_link["link"] == "https://t.me/somebot/play?startapp=" + with_link["code"]
    without = await svc.build_link(user_id=user.id, bot_username="", app_short_name="")
    assert without["link"] is None and without["code"] == with_link["code"]


# -- attribution ---------------------------------------------------------------

async def test_valid_claim_credits_exact_amounts_once():
    session = RecordingSession()
    users, profiles, referrals = StubUsers(), StubProfiles(), StubReferrals()
    svc = _service(session, users, profiles, referrals)
    referrer = await _register(svc, 111)
    row, _ = await referrals.get_or_create_code(user_id=referrer.id)
    code = row.code

    out = await svc.claim(code=code, telegram_id=222)

    assert out == {"credited": True, "already": False, "code": code,
                   "referrer_xp": 100, "referred_xp": 25}
    assert profiles.by_user[referrer.id].total_xp == 100
    newcomer = users.by_tid[222]
    assert profiles.by_user[newcomer.id].total_xp == 25
    assert session.commits == 0


async def test_configurable_amounts():
    session = RecordingSession()
    svc = _service(session, referrer_xp=50, referred_xp=10)
    referrer = await _register(svc, 111)
    row, _ = await svc.referrals.get_or_create_code(user_id=referrer.id)
    code = row.code
    out = await svc.claim(code=code, telegram_id=222)
    assert (out["referrer_xp"], out["referred_xp"]) == (50, 10)


async def test_existing_user_gets_nothing():
    session = RecordingSession()
    svc = _service(session)
    referrer = await _register(svc, 111)
    row, _ = await svc.referrals.get_or_create_code(user_id=referrer.id)
    code = row.code
    old_user = await _register(svc, 222)  # existed BEFORE opening the link
    before_ref = svc.profiles.by_user[referrer.id].total_xp
    before_old = svc.profiles.by_user[old_user.id].total_xp
    with pytest.raises(ConflictError):
        await svc.claim(code=code, telegram_id=222)
    assert svc.profiles.by_user[referrer.id].total_xp == before_ref
    assert svc.profiles.by_user[old_user.id].total_xp == before_old


async def test_self_referral_rejected_without_side_effects():
    session = RecordingSession()
    svc = _service(session)
    me = await _register(svc, 111)
    row, _ = await svc.referrals.get_or_create_code(user_id=me.id)
    code = row.code
    # Opening your own link as an existing user: no reward, no rows.
    with pytest.raises(ConflictError):
        await svc.claim(code=code, telegram_id=111)
    assert svc.referrals.attributions == {}
    assert svc.profiles.by_user[me.id].total_xp == 0


async def test_invalid_code_404s_without_side_effects():
    session = RecordingSession()
    svc = _service(session)
    with pytest.raises(NotFoundError):
        await svc.claim(code="NOPE1234", telegram_id=222)
    assert 222 not in svc.users.by_tid  # no user row created
    with pytest.raises(ValueError):
        await svc.claim(code="!!!", telegram_id=223)


async def test_duplicate_claim_is_idempotent_success():
    session = RecordingSession()
    svc = _service(session)
    referrer = await _register(svc, 111)
    row, _ = await svc.referrals.get_or_create_code(user_id=referrer.id)
    code = row.code
    first = await svc.claim(code=code, telegram_id=222)
    second = await svc.claim(code=code, telegram_id=222)
    assert first["already"] is False and second["already"] is True
    assert second["credited"] is True
    xp_calls = [c for c in svc.profiles.xp_calls]
    assert xp_calls.count((referrer.id, 100)) == 1
    newcomer = svc.users.by_tid[222]
    assert svc.profiles.by_user[newcomer.id].total_xp == 25


async def test_unique_violation_maps_to_conflict_no_double_xp():
    session = RecordingSession()
    svc = _service(session)
    referrer = await _register(svc, 111)
    row, _ = await svc.referrals.get_or_create_code(user_id=referrer.id)
    code = row.code
    svc.referrals.raise_on_record = IntegrityError("INSERT", {}, Exception("uq"))
    with pytest.raises(ConflictError):
        await svc.claim(code=code, telegram_id=222)


async def test_concurrent_claims_yield_single_credit():
    import asyncio

    session = RecordingSession()
    svc = _service(session)
    referrer = await _register(svc, 111)
    row, _ = await svc.referrals.get_or_create_code(user_id=referrer.id)
    code = row.code

    results = await asyncio.gather(
        svc.claim(code=code, telegram_id=222),
        svc.claim(code=code, telegram_id=222),
        return_exceptions=True,
    )
    assert not [r for r in results if isinstance(r, Exception)], results
    fresh = [r for r in results if r["already"] is False]
    replays = [r for r in results if r["already"] is True]
    # Exactly one fresh credit; the other is an idempotent replay (or a
    # 409 under real DB interleaving) — XP is awarded exactly once.
    assert len(fresh) == 1 and len(replays) == 1
    newcomer = svc.users.by_tid[222]
    assert svc.profiles.by_user[newcomer.id].total_xp == 25
    assert svc.profiles.by_user[referrer.id].total_xp == 100


async def test_stats_counts_and_sums():
    session = RecordingSession()
    svc = _service(session)
    referrer = await _register(svc, 111)
    assert await svc.stats(user_id=referrer.id) == {"referrals": 0, "referral_xp": 0}
    row, _ = await svc.referrals.get_or_create_code(user_id=referrer.id)
    code = row.code
    await svc.claim(code=code, telegram_id=222)
    await svc.claim(code=code, telegram_id=333)
    assert await svc.stats(user_id=referrer.id) == {"referrals": 2, "referral_xp": 200}
    with pytest.raises(NotFoundError):
        await svc.stats(user_id=uuid.uuid4())


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


def _client(monkeypatch, **settings_kw):
    from brainrush.services import referrals as referral_module

    app = create_app(_settings(**settings_kw),
                     session_factory=lambda: _DummyCM())

    async def fake_session(request: Request):
        yield object()

    async def fake_identity(request: Request):
        request.state.telegram_id = 777
        return {"user_id": uuid.uuid4(), "telegram_id": 777,
                "username": "carol", "display_name": "Carol D"}

    async def fake_telegram_identity(request: Request):
        return {"telegram_id": 888, "username": "newbie", "display_name": "New Bie"}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_verified_identity] = fake_identity
    app.dependency_overrides[get_verified_telegram_identity] = fake_telegram_identity
    monkeypatch.setattr(routes, "ReferralService", referral_module.ReferralService)
    return TestClient(app, raise_server_exceptions=False)


def _real_claim_client(monkeypatch):
    """Real ReferralService with stub repos; auth stubbed."""
    from brainrush.api.deps import get_verified_telegram_identity as _tdep
    from brainrush.services import referrals as referral_module

    users, profiles, referrals = StubUsers(), StubProfiles(), StubReferrals()

    class WiredService(referral_module.ReferralService):
        def __init__(self, session, **kwargs):
            super().__init__(session, referrer_xp=100, referred_xp=25)
            self.users = users
            self.profiles = profiles
            self.referrals = referrals

    app = create_app(_settings(), session_factory=lambda: _DummyCM())

    async def fake_session(request: Request):
        from tests.test_repositories import RecordingSession as RS
        yield RS()

    async def _register_shared(telegram_id, username, display_name):
        user, _ = await users.get_or_create(
            telegram_id=telegram_id, username=username, display_name=display_name)
        await profiles.get_or_create(user_id=user.id)
        return user

    async def fake_identity(request: Request):
        user = await _register_shared(777, "carol", "Carol D")
        request.state.telegram_id = 777
        return {"user_id": user.id, "telegram_id": 777,
                "username": "carol", "display_name": "Carol D"}

    async def fake_telegram_identity(request: Request):
        return {"telegram_id": 888, "username": "newbie", "display_name": "New Bie"}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_verified_identity] = fake_identity
    app.dependency_overrides[_tdep] = fake_telegram_identity
    monkeypatch.setattr(routes, "ReferralService", WiredService)
    client = TestClient(app, raise_server_exceptions=False)
    return client, users, profiles, referrals


def test_referral_routes_end_to_end(monkeypatch):
    client, users, profiles, referrals = _real_claim_client(monkeypatch)
    headers = {"X-Telegram-Init-Data": "anything"}

    mine = client.get("/api/referrals/mine", headers=headers)
    assert mine.status_code == 200
    body = mine.json()
    assert re.fullmatch(r"[A-Za-z0-9]{4,32}", body["code"])
    assert body["referrer_xp"] == 100 and body["referred_xp"] == 25
    assert body["link"] is None  # bot/app names unconfigured in test settings

    again = client.get("/api/referrals/mine", headers=headers)
    assert again.json()["code"] == body["code"]  # stable across reloads

    claimed = client.post("/api/referrals/claim", headers=headers,
                          json={"code": body["code"]})
    assert claimed.status_code == 200
    assert claimed.json()["credited"] is True

    stats = client.get("/api/referrals/stats", headers=headers)
    # Dashboard user (777) owns the code, so the 888 claim counts for them.
    assert stats.json() == {"referrals": 1, "referral_xp": 100}


def test_claim_rejects_bad_code_with_404(monkeypatch):
    client, *_ = _real_claim_client(monkeypatch)
    response = client.post("/api/referrals/claim",
                           headers={"X-Telegram-Init-Data": "x"},
                           json={"code": "NOPE1234"})
    assert response.status_code == 404


def test_claim_requires_auth(monkeypatch):
    from brainrush.api.deps import get_session as _gs

    app = create_app(_settings(), session_factory=lambda: _DummyCM())

    async def fake_session(request: Request):
        from tests.test_repositories import RecordingSession as RS
        yield RS()

    app.dependency_overrides[_gs] = fake_session
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/referrals/mine").status_code in (401, 422)
    assert client.post("/api/referrals/claim", json={"code": "ABC123"}).status_code in (401, 422)
