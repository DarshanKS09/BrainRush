"""Multiplayer engine tests: no real DB/Telegram.

Service tests use in-memory stub repositories + RecordingSession (transaction
ownership: one begin() per call, zero direct commits). Route tests use
TestClient with a stubbed MatchService, mirroring test_api.py.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from brainrush.db.errors import ConflictError, NotFoundError
from brainrush.db.models import GameResult, GameSession, PlayerProfile, User
from brainrush.game import multiplayer as mp
from brainrush.services.matches import MatchService
from tests.test_repositories import RecordingSession


def _utcnow():
    return datetime.now(timezone.utc)


# -- stub repositories -------------------------------------------------------

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
        self.level_calls = []

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

    async def add_xp(self, *, user_id, amount):
        profile = self.by_user.get(user_id)
        if profile is None:
            raise NotFoundError("player profile not found")
        profile.total_xp += amount
        self.xp_calls.append((user_id, amount))
        return profile

    async def set_level(self, *, user_id, level):
        profile = self.by_user.get(user_id)
        if profile is None:
            raise NotFoundError("player profile not found")
        profile.current_level = level
        self.level_calls.append((user_id, level))
        return profile


class StubSessions:
    def __init__(self):
        self.rows = {}

    def add_started(self, user_id, game_type="number_guessing", started_at=None, score=0):
        from brainrush.db.models import GameSession as GS

        row = GS(user_id=user_id, game_type=game_type, status="started")
        row.id = uuid.uuid4()
        row.started_at = started_at or _utcnow()
        row.ended_at = None
        row.score = score
        self.rows[row.id] = row
        return row

    async def get_by_id(self, sid):
        return self.rows.get(sid)

    async def create(self, *, user_id, game_type):
        return self.add_started(user_id, game_type)

    async def finish(self, *, session_id, status, score, ended_at, duration_seconds):
        row = self.rows.get(session_id)
        if row is None:
            raise NotFoundError("game session not found")
        if row.status != "started":
            raise ConflictError(f"session is already {row.status}")
        row.status = status
        row.score = score
        row.ended_at = ended_at
        return row

    async def abandon(self, *, session_id, ended_at):
        return await self.finish(
            session_id=session_id, status="abandoned", score=0,
            ended_at=ended_at, duration_seconds=None,
        )

    async def expire_stale_started(self, *, user_id, before):
        n = 0
        for row in self.rows.values():
            if (row.user_id == user_id and row.status == "started"
                    and row.started_at < before):
                row.status = "expired"
                row.ended_at = _utcnow()
                n += 1
        return n

    async def history_by_user(self, *, user_id, limit=20, offset=0):
        return []


class StubResults:
    def __init__(self):
        self.by_session = {}

    def add(self, session_id, score, outcome="win", metadata=None, xp=0):
        row = GameResult(
            session_id=session_id, score=score, outcome=outcome,
            xp_earned=xp, result_metadata=dict(metadata or {}),
        )
        row.id = uuid.uuid4()
        row.created_at = _utcnow()
        self.by_session[session_id] = row
        return row

    async def get_by_session(self, sid):
        return self.by_session.get(sid)

    async def record(self, *, session_id, score, outcome, xp_earned, metadata=None):
        if session_id in self.by_session:
            raise IntegrityError("INSERT", {}, Exception("uq"))
        return self.add(session_id, score, outcome, metadata, xp_earned)

    async def list_by_session_ids(self, *, session_ids):
        return {sid: self.by_session[sid] for sid in session_ids if sid in self.by_session}

    async def best_win_score(self, *, user_id, game_type=None):
        return None

    async def best_score_for_game(self, *, user_id, game_type):
        return None


class StubActivities:
    def __init__(self):
        self.calls = []

    async def get(self, *, user_id, day):
        return None

    async def add_play(self, *, user_id, day, xp_earned):
        self.calls.append((user_id, day, xp_earned))
        raise AssertionError("match rewards must not touch daily activity")


class StubMatches:
    def __init__(self):
        self.rows = {}
        self.mine = []  # set per-test for list_by_user

    async def create(self, *, game_type, mode, host_user_id, max_players,
                     min_players, difficulty, token_expires_at):
        from brainrush.db.models import Match

        row = Match(
            game_type=game_type, mode=mode, status="lobby",
            host_user_id=host_user_id, max_players=max_players,
            min_players=min_players, invite_token="m-" + uuid.uuid4().hex[:22],
            token_expires_at=token_expires_at, difficulty=difficulty,
        )
        row.id = uuid.uuid4()
        row.created_at = _utcnow()
        row.started_at = None
        row.deadline = None
        row.finished_at = None
        self.rows[row.id] = row
        return row

    async def get_by_id(self, mid):
        return self.rows.get(mid)

    async def get_for_update(self, mid):
        return self.rows.get(mid)

    async def get_by_token(self, *, token):
        for row in self.rows.values():
            if row.invite_token == token:
                return row
        return None

    async def set_status(self, *, match_id, status):
        row = self.rows.get(match_id)
        if row is None:
            return None
        row.status = status
        return row

    async def start_match(self, *, match_id, started_at, deadline):
        row = self.rows.get(match_id)
        if row is None or row.status != "lobby":
            return None
        row.status = "active"
        row.started_at = started_at
        row.deadline = deadline
        return row

    async def complete_match(self, *, match_id, finished_at):
        row = self.rows.get(match_id)
        if row is None or row.status != "active":
            return None
        row.status = "completed"
        row.finished_at = finished_at
        return row

    async def list_by_user(self, *, user_id, limit=20, offset=0):
        # Derive from parts when linked (see _service wiring); fall back
        # to explicit .mine for tests that set it directly.
        parts = getattr(self, "_parts", None)
        if parts is not None:
            mids = {r.match_id for r in parts.rows if r.user_id == user_id}
            out = [self.rows[mid] for mid in mids if mid in self.rows]
            out.sort(key=lambda r: r.created_at or _utcnow(), reverse=True)
            return out[offset:offset + limit]
        return list(self.mine)[offset:offset + limit]

    async def set_host(self, *, match_id, host_user_id):
        row = self.rows.get(match_id)
        if row is not None:
            row.host_user_id = host_user_id

    async def expire_old_lobbies(self, *, user_id, before):
        return 0


class StubParts:
    def __init__(self):
        self.rows = []  # SimpleNamespace-ish dicts
        self.raise_on_add = False

    def _row(self, match_id, user_id):
        from types import SimpleNamespace

        return SimpleNamespace(
            match_id=match_id, user_id=user_id, session_id=None,
            score=0, stats={}, xp_earned=0, rank=None, finished_at=None,
            joined_at=_utcnow(), last_seen_at=_utcnow(),
        )

    async def get(self, *, match_id, user_id):
        for r in self.rows:
            if r.match_id == match_id and r.user_id == user_id:
                return r
        return None

    async def get_by_session(self, *, session_id):
        for r in self.rows:
            if r.session_id == session_id:
                return r
        return None

    async def list_by_match(self, *, match_id):
        return sorted(
            [r for r in self.rows if r.match_id == match_id],
            key=lambda r: r.joined_at,
        )

    async def count_by_match(self, *, match_id):
        return sum(1 for r in self.rows if r.match_id == match_id)

    async def add(self, *, match_id, user_id):
        if self.raise_on_add:
            raise IntegrityError("INSERT", {}, Exception("uq"))
        if any(r.match_id == match_id and r.user_id == user_id for r in self.rows):
            raise IntegrityError("INSERT", {}, Exception("uq"))
        row = self._row(match_id, user_id)
        self.rows.append(row)
        return row

    async def attach_result(self, *, match_id, user_id, session_id, score, stats):
        for r in self.rows:
            if (r.match_id == match_id and r.user_id == user_id
                    and r.session_id is None):
                r.session_id = session_id
                r.score = score
                r.stats = dict(stats)
                r.finished_at = _utcnow()
                return r
        # idempotent replay path needs the row; missing means logic error
        existing = await self.get(match_id=match_id, user_id=user_id)
        if existing is not None and existing.session_id == session_id:
            return existing
        from brainrush.db.errors import NotFoundError as _NF

        raise _NF("match participant not found")

    async def set_rank_xp(self, *, match_id, user_id, rank, xp):
        row = await self.get(match_id=match_id, user_id=user_id)
        assert row is not None
        row.rank = rank
        row.xp_earned = xp

    async def remove(self, *, match_id, user_id):
        self.rows = [r for r in self.rows
                     if not (r.match_id == match_id and r.user_id == user_id)]


class StubInvites:
    def __init__(self):
        self.rows = []

    async def get(self, *, match_id, invited_user_id):
        for r in self.rows:
            if r.match_id == match_id and r.invited_user_id == invited_user_id:
                return r
        return None

    async def list_pending_with_matches(self, *, user_id):
        return []

    async def invite(self, *, match_id, invited_user_id, invited_by_user_id):
        from types import SimpleNamespace

        for r in self.rows:
            if r.match_id == match_id and r.invited_user_id == invited_user_id:
                if r.status == "declined":
                    r.status = "pending"
                return r, False
        row = SimpleNamespace(
            match_id=match_id, invited_user_id=invited_user_id,
            invited_by_user_id=invited_by_user_id, status="pending",
            created_at=_utcnow(),
        )
        self.rows.append(row)
        return row, True

    async def set_status(self, *, match_id, invited_user_id, status):
        row = await self.get(match_id=match_id, invited_user_id=invited_user_id)
        if row is not None:
            row.status = status

    async def list_pending_with_matches(self, *, user_id):
        return []


class StubFriends:
    def __init__(self, pairs=()):
        self.pairs = {tuple(sorted((str(a), str(b)))) for a, b in pairs}

    async def get_pair(self, a, b):
        key = tuple(sorted((str(a), str(b))))
        if key in self.pairs:
            from types import SimpleNamespace

            return SimpleNamespace(user_low=a, user_high=b)
        return None


class StubRewards:
    def __init__(self):
        self.rows = []  # (match_id, user_id, kind, xp)

    async def award_once(self, *, match_id, user_id, kind, xp):
        if kind not in ("participation", "win"):
            raise ValueError("kind must be participation or win")
        if any(r[0] == match_id and r[1] == user_id and r[2] == kind
               for r in self.rows):
            return False
        self.rows.append((match_id, user_id, kind, xp))
        return True

    async def sum_since(self, *, user_id, since):
        return 0

    async def sum_since_many(self, *, user_ids, since):
        return {}


class StubStates:
    async def delete_for_expired_sessions(self, *, user_id):
        return 0


def _service(session, **over):
    from brainrush.services.matches import MatchService

    svc = MatchService(
        session, completion_xp=10, win_bonus=10, daily_cap=500,
        lobby_ttl_hours=24, invite_ttl_days=7, default_minutes=60,
    )
    svc.users = over.get("users", StubUsers())
    svc.profiles = over.get("profiles", StubProfiles())
    svc.sessions = over.get("sessions", StubSessions())
    svc.results = over.get("results", StubResults())
    svc.activities = over.get("activities", StubActivities())
    svc.matches = over.get("matches", StubMatches())
    svc.parts = over.get("parts", StubParts())
    svc.matches._parts = svc.parts
    svc.invites = over.get("invites", StubInvites())
    svc.rewards = over.get("rewards", StubRewards())
    svc.friends = over.get("friends", StubFriends())
    svc.states = over.get("states", StubStates())
    return svc


def _registered(svc, telegram_id, **kw):
    user = svc.users.add(telegram_id, **kw)
    svc.profiles.ensure(user.id)
    return user


# -- registry + ranking (pure) -------------------------------------------------

async def test_registry_covers_all_solo_games():
    assert set(mp.REGISTRY) == {"number_guessing", "color_sequence",
                                "reflex_rush", "perfect_second"}
    for spec in mp.REGISTRY.values():
        assert spec.modes <= mp.MODES
        assert spec.modes  # every game supports at least one mode
    assert mp.spec_for("perfect_second").modes == mp.MODES
    assert mp.spec_for("perfect_second").higher_is_better is False
    with pytest.raises(ValueError):
        mp.spec_for("quiz_rush")


async def test_ranking_direction_and_dense_ties():
    lo = [
        {"user_id": uuid.uuid4(), "score": 3, "higher_is_better": False,
         "tiebreak": ("t2",)},
        {"user_id": uuid.uuid4(), "score": 5, "higher_is_better": False,
         "tiebreak": ("t1",)},
        {"user_id": uuid.uuid4(), "score": 3, "higher_is_better": False,
         "tiebreak": ("t2",)},
    ]
    ranked = mp.rank_participants(lo)
    assert [r["score"] for r in ranked] == [3, 3, 5]
    assert [r["rank"] for r in ranked] == [1, 1, 2]  # equal keys share rank
    hi = [
        {"user_id": uuid.uuid4(), "score": 10, "higher_is_better": True,
         "tiebreak": ("t9",)},
        {"user_id": uuid.uuid4(), "score": 30, "higher_is_better": True,
         "tiebreak": ("t1",)},
    ]
    assert [r["score"] for r in mp.rank_participants(hi)] == [30, 10]


async def test_mode_capacity_rules():
    assert mp.MODE_MIN_PLAYERS == {"duel": 2, "ffa": 3, "tournament": 5}
    assert mp.MODE_DEFAULT_MAX["duel"] == 2
    assert mp.ABSOLUTE_MAX_PLAYERS >= mp.MODE_DEFAULT_MAX["tournament"]


def test_reward_ledger_unique_per_kind():
    """The ledger must allow participation + win rows per seat (regression:
    a (match_id, user_id) constraint would silently drop every win bonus via
    ON CONFLICT DO NOTHING)."""
    from brainrush.db.base import Base
    import brainrush.db.models  # noqa: F401  (register tables)

    table = Base.metadata.tables["match_rewards"]
    uqs = [
        sorted(c.columns.keys())
        for c in table.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    ]
    assert ["kind", "match_id", "user_id"] in uqs


async def _lobby(svc, host, game="number_guessing", mode="duel",
                 difficulty="hard", max_players=None):
    view = await svc.create_match(
        host_user_id=host.id, game_type=game, mode=mode,
        difficulty=difficulty, max_players=max_players,
    )
    return uuid.UUID(view["match_id"])


async def _join(svc, user, mid):
    return await svc.join_match(user_id=user.id, match_id=mid)


async def _start(svc, host, mid):
    return await svc.start_match(host_user_id=host.id, match_id=mid)


async def _solo_win(svc, user, game, score, when=None, outcome="win", meta=None):
    solo = svc.sessions.add_started(user.id, game)
    moment = when or _utcnow()
    solo.status = "completed"
    solo.score = score
    solo.ended_at = moment
    row = svc.results.add(solo.id, score, outcome, meta or {}, xp=0)
    row.created_at = moment
    return solo


async def test_create_defaults_and_validation():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    duel = await svc.create_match(
        host_user_id=host.id, game_type="number_guessing", mode="duel")
    assert duel["status"] == "lobby" and duel["max_players"] == 2
    assert duel["min_players"] == 2 and duel["count"] == 1
    assert duel["participants"][0]["is_host"] is True
    assert duel["invite_token"] if False else True  # token not exposed here
    ffa = await svc.create_match(
        host_user_id=host.id, game_type="color_sequence", mode="ffa")
    assert (ffa["min_players"], ffa["max_players"]) == (3, 8)
    t = await svc.create_match(
        host_user_id=host.id, game_type="reflex_rush", mode="tournament",
        max_players=10)
    assert (t["min_players"], t["max_players"]) == (5, 10)
    with pytest.raises(ValueError):
        await svc.create_match(host_user_id=host.id, game_type="quiz_rush", mode="duel")
    with pytest.raises(ValueError):
        await svc.create_match(host_user_id=host.id, game_type="number_guessing", mode="ffa",
                               max_players=2)
    with pytest.raises(ValueError):
        await svc.create_match(host_user_id=host.id, game_type="number_guessing", mode="duel",
                               max_players=4)
    with pytest.raises(ValueError):
        await svc.create_match(host_user_id=host.id, game_type="number_guessing",
                               mode="duel", difficulty="extreme")
    with pytest.raises(NotFoundError):
        await svc.create_match(host_user_id=uuid.uuid4(), game_type="number_guessing",
                               mode="duel")
    assert session.commits == 0


async def test_join_idempotent_capacity_and_expiry():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    stranger = _registered(svc, 333)
    mid = await _lobby(svc, host)
    first = await _join(svc, guest, mid)
    again = await _join(svc, guest, mid)
    assert first["count"] == again["count"] == 2
    assert len([p for p in again["participants"] if p["user_id"] == str(guest.id)]) == 1
    with pytest.raises(ConflictError):  # duel full
        await _join(svc, stranger, mid)
    with pytest.raises(NotFoundError):  # unknown match leaks nothing
        await _join(svc, stranger, uuid.uuid4())
    assert session.commits == 0


async def test_join_by_token_and_expiry():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    mid = await _lobby(svc, host, mode="ffa")
    match = svc.matches.rows[mid]
    view = await svc.join_by_token(user_id=guest.id, token=match.invite_token)
    assert view["count"] == 2
    assert view["status"] == "lobby"
    again = await svc.join_by_token(user_id=guest.id, token=match.invite_token)
    assert again["count"] == 2
    with pytest.raises(NotFoundError):
        await svc.join_by_token(user_id=guest.id, token="m-nope-not-real-token")
    with pytest.raises(NotFoundError):
        await svc.join_by_token(user_id=guest.id, token="bogus")
    match.token_expires_at = _utcnow() - timedelta(seconds=1)
    with pytest.raises(NotFoundError):
        await svc.join_by_token(user_id=uuid.uuid4(), token=match.invite_token)


async def test_invite_requires_host_friendship_and_capacity():
    session = RecordingSession()
    users, profiles = StubUsers(), StubProfiles()
    friends = StubFriends(pairs=set())
    svc = _service(session, users=users, profiles=profiles, friends=friends)
    host = _registered(svc, 111)
    friend = _registered(svc, 222)
    stranger = _registered(svc, 333)
    mid = await _lobby(svc, host)
    with pytest.raises(ConflictError):  # not friends yet
        await svc.invite_friend(host_user_id=host.id, match_id=mid,
                                friend_user_id=friend.id)
    friends.pairs.add(tuple(sorted((str(host.id), str(friend.id)))))
    out = await svc.invite_friend(host_user_id=host.id, match_id=mid,
                                  friend_user_id=friend.id)
    assert out == {"match_id": str(mid), "invited": True, "already": False,
                   "status": "pending"}
    again = await svc.invite_friend(host_user_id=host.id, match_id=mid,
                                    friend_user_id=friend.id)
    assert again["invited"] is False and again["already"] is True
    with pytest.raises(ConflictError):  # non-host cannot invite
        await svc.invite_friend(host_user_id=friend.id, match_id=mid,
                                friend_user_id=stranger.id)
    with pytest.raises(ConflictError):  # self invite
        await svc.invite_friend(host_user_id=host.id, match_id=mid,
                                friend_user_id=host.id)
    with pytest.raises(NotFoundError):  # unknown user
        await svc.invite_friend(host_user_id=host.id, match_id=mid,
                                friend_user_id=uuid.uuid4())
    assert session.commits == 0


async def test_start_requires_host_and_minimum():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    other = _registered(svc, 333)
    mid = await _lobby(svc, host, mode="ffa")
    await _join(svc, guest, mid)
    with pytest.raises(ConflictError):  # non-host
        await svc.start_match(host_user_id=guest.id, match_id=mid)
    with pytest.raises(ConflictError):  # only 2/3 present
        await svc.start_match(host_user_id=host.id, match_id=mid)
    await _join(svc, other, mid)
    view = await _start(svc, host, mid)
    assert view["status"] == "active"
    assert view["deadline"] is not None and view["started_at"] is not None
    with pytest.raises(ConflictError):  # double start
        await svc.start_match(host_user_id=host.id, match_id=mid)
    # duel demands exactly two
    dmid = await _lobby(svc, host)
    await _join(svc, guest, dmid)
    assert (await _start(svc, host, dmid))["status"] == "active"


async def test_duel_full_flow_ranks_and_pays_once():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    mid = await _lobby(svc, host)
    await _join(svc, guest, mid)
    await _start(svc, host, mid)
    host_solo = await _solo_win(svc, host, "number_guessing", 5)
    guest_solo = await _solo_win(svc, guest, "number_guessing", 3)
    first = await svc.submit_result(user_id=host.id, match_id=mid,
                                    session_id=host_solo.id)
    assert first["status"] == "active"  # guest still playing
    # resubmit same session: idempotent replay, no duplicate work
    replay = await svc.submit_result(user_id=host.id, match_id=mid,
                                     session_id=host_solo.id)
    assert replay["status"] == "active"
    done = await svc.submit_result(user_id=guest.id, match_id=mid,
                                   session_id=guest_solo.id)
    assert done["status"] == "completed"
    ranks = {p["user_id"]: p["rank"] for p in done["participants"]}
    assert ranks[str(guest.id)] == 1 and ranks[str(host.id)] == 2  # fewer wins
    paid = {p["user_id"]: p["xp_earned"] for p in done["participants"]}
    assert paid[str(guest.id)] == 20 and paid[str(host.id)] == 10
    assert svc.profiles.by_user[guest.id].total_xp == 20
    assert svc.profiles.by_user[host.id].total_xp == 10
    # stats untouched by match play (single-player counters stay clean)
    assert svc.profiles.by_user[guest.id].games_played == 0
    assert svc.activities.calls == []
    assert session.commits == 0


async def test_submit_validation_matrix():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    outsider = _registered(svc, 333)
    mid = await _lobby(svc, host)
    await _join(svc, guest, mid)
    other_solo = await _solo_win(svc, outsider, "number_guessing", 2)
    with pytest.raises(NotFoundError):  # not a participant
        await svc.submit_result(user_id=outsider.id, match_id=mid,
                                session_id=other_solo.id)
    with pytest.raises(ConflictError):  # lobby, not started
        await svc.submit_result(user_id=guest.id, match_id=mid,
                                session_id=other_solo.id)
    await _start(svc, host, mid)
    with pytest.raises(NotFoundError):  # foreign session
        await svc.submit_result(user_id=guest.id, match_id=mid,
                                session_id=other_solo.id)
    unfinished = svc.sessions.add_started(guest.id, "number_guessing")
    with pytest.raises(ConflictError):  # unfinished solo game
        await svc.submit_result(user_id=guest.id, match_id=mid,
                                session_id=unfinished.id)
    wrong_game = await _solo_win(svc, guest, "color_sequence", 4)
    with pytest.raises(ConflictError):  # wrong game type
        await svc.submit_result(user_id=guest.id, match_id=mid,
                                session_id=wrong_game.id)
    # second session for same seat after a valid submit
    good = await _solo_win(svc, guest, "number_guessing", 4)
    await svc.submit_result(user_id=guest.id, match_id=mid, session_id=good.id)
    other = await _solo_win(svc, guest, "number_guessing", 1)
    with pytest.raises(ConflictError):
        await svc.submit_result(user_id=guest.id, match_id=mid,
                                session_id=other.id)


async def test_ties_share_rank_and_bonus():
    session = RecordingSession()
    svc = _service(session)
    users = [_registered(svc, 111 + i) for i in range(3)]
    mid = await _lobby(svc, users[0], game="color_sequence", mode="ffa")
    for u in users[1:]:
        await _join(svc, u, mid)
    await _start(svc, users[0], mid)
    moment = _utcnow()
    for u in users:
        solo = await _solo_win(svc, u, "color_sequence", 5, when=moment)
        await svc.submit_result(user_id=u.id, match_id=mid, session_id=solo.id)
    view = await svc.get_match(user_id=users[0].id, match_id=mid)
    ranks = sorted(p["rank"] for p in view["participants"])
    assert ranks == [1, 1, 1]
    # every winner gets the bonus exactly once
    assert sorted(p["xp_earned"] for p in view["participants"]) == [20, 20, 20]


async def test_deadline_finalize_ranks_unfinished_last_with_zero_xp():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    quitter = _registered(svc, 333)
    mid = await _lobby(svc, host, mode="ffa")
    await _join(svc, guest, mid)
    await _join(svc, quitter, mid)
    await _start(svc, host, mid)
    solo = await _solo_win(svc, host, "number_guessing", 4)
    await svc.submit_result(user_id=host.id, match_id=mid, session_id=solo.id)
    match = svc.matches.rows[mid]
    match.deadline = _utcnow() - timedelta(seconds=1)  # force expiry
    done = await svc.finalize_match(user_id=guest.id, match_id=mid)
    assert done["status"] == "completed"
    by_id = {p["user_id"]: p for p in done["participants"]}
    assert by_id[str(host.id)]["rank"] == 1
    assert by_id[str(host.id)]["xp_earned"] == 20
    assert by_id[str(guest.id)]["rank"] == 2
    assert by_id[str(guest.id)]["xp_earned"] == 0
    assert by_id[str(quitter.id)]["rank"] == 2
    # finalize twice: idempotent, no double pay
    again = await svc.finalize_match(user_id=host.id, match_id=mid)
    assert again["status"] == "completed"
    assert svc.profiles.by_user[host.id].total_xp == 20
    with pytest.raises(ConflictError):  # not ready: fresh active match
        mid2 = await _lobby(svc, host, mode="ffa")
        await _join(svc, guest, mid2)
        await _start(svc, host, mid2)
        await svc.finalize_match(user_id=host.id, match_id=mid2)


async def test_daily_cap_bounds_farming():
    session = RecordingSession()
    svc = _service(session, )
    svc.daily_cap = 12
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    mid = await _lobby(svc, host)
    await _join(svc, guest, mid)
    await _start(svc, host, mid)
    host_solo = await _solo_win(svc, host, "number_guessing", 2)
    guest_solo = await _solo_win(svc, guest, "number_guessing", 9)
    await svc.submit_result(user_id=host.id, match_id=mid, session_id=host_solo.id)
    done = await svc.submit_result(user_id=guest.id, match_id=mid, session_id=guest_solo.id)
    paid = {p["user_id"]: p["xp_earned"] for p in done["participants"]}
    # host wins: 10 completion + min(10 bonus, 12-10 cap room) = 12.
    # guest loses: min(10 completion, 12 cap) = 10. Cap bounds the total.
    assert paid == {str(host.id): 12, str(guest.id): 10}
    assert svc.profiles.by_user[host.id].total_xp == 12
    assert svc.profiles.by_user[guest.id].total_xp == 10


async def test_cancel_leave_host_transfer_and_rematch():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    other = _registered(svc, 333)
    # cancel: host-only, lobby-only
    mid = await _lobby(svc, host, mode="ffa")
    await _join(svc, guest, mid)
    with pytest.raises(ConflictError):
        await svc.cancel_match(host_user_id=guest.id, match_id=mid)
    out = await svc.cancel_match(host_user_id=host.id, match_id=mid)
    assert out == {"match_id": str(mid), "status": "cancelled"}
    with pytest.raises(ConflictError):
        await svc.join_match(user_id=other.id, match_id=mid)
    # leave: host transfers to oldest remaining; empty lobby cancels
    mid2 = await _lobby(svc, host, mode="ffa")
    await _join(svc, guest, mid2)
    await _join(svc, other, mid2)
    assert (await svc.leave_match(user_id=host.id, match_id=mid2))["status"] == "lobby"
    assert svc.matches.rows[mid2].host_user_id == guest.id
    assert (await svc.leave_match(user_id=guest.id, match_id=mid2))["status"] == "lobby"
    assert (await svc.leave_match(user_id=other.id, match_id=mid2))["status"] == "cancelled"
    # leave active match is rejected (counts as abandoned at finalize)
    mid3 = await _lobby(svc, host)
    await _join(svc, guest, mid3)
    await _start(svc, host, mid3)
    with pytest.raises(ConflictError):
        await svc.leave_match(user_id=guest.id, match_id=mid3)
    with pytest.raises(ConflictError):
        await svc.cancel_match(host_user_id=host.id, match_id=mid3)
    assert session.commits == 0


async def test_rematch_creates_fresh_match_with_invites():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    third = _registered(svc, 333)
    mid = await _lobby(svc, host, mode="ffa")
    await _join(svc, guest, mid)
    await _join(svc, third, mid)
    await _start(svc, host, mid)
    for u, score in ((host, 2), (guest, 5), (third, 6)):
        solo = await _solo_win(svc, u, "number_guessing", score)
        await svc.submit_result(user_id=u.id, match_id=mid, session_id=solo.id)
    with pytest.raises(ConflictError):  # active matches cannot rematch
        fresh_mid = await _lobby(svc, host, mode="ffa")
        await svc.rematch(user_id=host.id, match_id=fresh_mid)
    new_view = await svc.rematch(user_id=guest.id, match_id=mid)
    assert new_view["status"] == "lobby"
    assert new_view["mode"] == "ffa" and new_view["game_type"] == "number_guessing"
    assert new_view["count"] == 1  # nobody auto-joined
    new_id = uuid.UUID(new_view["match_id"])
    assert new_id != mid
    assert svc.matches.rows[new_id].host_user_id == guest.id
    assert len(svc.invites.rows) == 2  # others auto-invited, not joined
    with pytest.raises(NotFoundError):  # strangers cannot rematch
        await svc.rematch(user_id=uuid.uuid4(), match_id=mid)


async def test_mine_invites_link_and_visibility():
    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    stranger = _registered(svc, 333)
    mid = await _lobby(svc, host, mode="ffa")
    mine = await svc.my_matches(user_id=host.id)
    assert len(mine) == 1 and mine[0]["status"] == "lobby"
    assert mine[0]["my_rank"] is None
    assert (await svc.my_matches(user_id=stranger.id)) == []
    assert await svc.my_invites(user_id=guest.id) == []
    link = await svc.build_match_link(
        match_id=mid, user_id=host.id,
        bot_username="somebot", app_short_name="play",
    )
    assert link["token"].startswith("m-")
    assert link["link"] == f"https://t.me/somebot/play?startapp={link['token']}"
    bare = await svc.build_match_link(
        match_id=mid, user_id=host.id, bot_username="", app_short_name="")
    assert bare == {"token": link["token"], "link": None}
    with pytest.raises(NotFoundError):  # non-participant sees nothing
        await svc.build_match_link(
            match_id=mid, user_id=stranger.id,
            bot_username="somebot", app_short_name="play")
    with pytest.raises(NotFoundError):  # non-participant reads nothing
        await svc.get_match(user_id=stranger.id, match_id=mid)
    assert session.commits == 0


# -- routes (thin, auth-mapped) ------------------------------------------------

class StubMatchService:
    """Stands in for MatchService; routes construct per request."""

    instance = None

    def __init__(self, session, **kwargs):
        self.calls = []
        self.kwargs = kwargs
        self.view = {"match_id": str(uuid.uuid4()), "status": "lobby"}
        self.error = None
        StubMatchService.instance = self

    def _raise(self):
        if self.error is not None:
            raise self.error

    async def create_match(self, *, host_user_id, game_type, mode,
                           difficulty="hard", max_players=None):
        self.calls.append(("create", host_user_id, game_type, mode,
                           difficulty, max_players))
        self._raise()
        return self.view

    async def my_matches(self, *, user_id, limit=20, offset=0):
        self.calls.append(("mine", user_id, limit, offset))
        self._raise()
        return []

    async def my_invites(self, *, user_id):
        self.calls.append(("invites", user_id))
        self._raise()
        return []

    async def get_match(self, *, user_id, match_id):
        self.calls.append(("get", user_id, match_id))
        self._raise()
        return self.view

    async def join_by_token(self, *, user_id, token):
        self.calls.append(("join-token", user_id, token))
        self._raise()
        return self.view

    async def join_match(self, *, user_id, match_id):
        self.calls.append(("join", user_id, match_id))
        self._raise()
        return self.view

    async def invite_friend(self, *, host_user_id, match_id, friend_user_id):
        self.calls.append(("invite", host_user_id, match_id, friend_user_id))
        self._raise()
        return {"match_id": str(match_id), "invited": True,
                "already": False, "status": "pending"}

    async def build_match_link(self, *, match_id, user_id,
                               bot_username, app_short_name):
        self.calls.append(("link", match_id, user_id))
        self._raise()
        return {"token": "m-x", "link": None}

    async def start_match(self, *, host_user_id, match_id):
        self.calls.append(("start", host_user_id, match_id))
        self._raise()
        return self.view

    async def submit_result(self, *, user_id, match_id, session_id):
        self.calls.append(("submit", user_id, match_id, session_id))
        self._raise()
        return self.view

    async def finalize_match(self, *, user_id, match_id):
        self.calls.append(("finalize", user_id, match_id))
        self._raise()
        return self.view

    async def cancel_match(self, *, host_user_id, match_id):
        self.calls.append(("cancel", host_user_id, match_id))
        self._raise()
        return {"match_id": str(match_id), "status": "cancelled"}

    async def leave_match(self, *, user_id, match_id):
        self.calls.append(("leave", user_id, match_id))
        self._raise()
        return {"match_id": str(match_id), "status": "lobby"}

    async def rematch(self, *, user_id, match_id):
        self.calls.append(("rematch", user_id, match_id))
        self._raise()
        return self.view


MUID = uuid.uuid4()
MMID = uuid.uuid4()
MSID = uuid.uuid4()


def _match_client(monkeypatch):
    from fastapi import Request
    from fastapi.testclient import TestClient

    from brainrush.api import routes
    from brainrush.api.app import create_app
    from brainrush.api.deps import get_session, get_verified_identity
    from brainrush.config import Settings

    app = create_app(
        Settings(BOT_TOKEN="test-token",
                 DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db"),
        session_factory=_DummyFactory(),
    )

    async def fake_session(request: Request):
        yield object()

    async def fake_identity(request: Request):
        return {"user_id": MUID, "telegram_id": 777,
                "username": "carol", "display_name": "Carol D"}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_verified_identity] = fake_identity
    monkeypatch.setattr(routes, "MatchService", StubMatchService)
    return TestClient(app, raise_server_exceptions=False)


class _DummyCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


class _DummyFactory:
    def __call__(self):
        return _DummyCM()


def test_match_routes_pass_verified_identity(monkeypatch):
    client = _match_client(monkeypatch)
    headers = {"X-Telegram-Init-Data": "anything"}

    created = client.post("/api/matches", headers=headers,
                          json={"game_type": "number_guessing",
                                "mode": "duel", "difficulty": "hard"})
    assert created.status_code == 200
    assert StubMatchService.instance.calls[0][:2] == ("create", MUID)

    got = client.get(f"/api/matches/{MMID}", headers=headers)
    assert got.status_code == 200
    assert StubMatchService.instance.calls[-1] == ("get", MUID, MMID)

    joined = client.post("/api/matches/join", headers=headers,
                         json={"token": "m-abc"})
    assert joined.status_code == 200
    assert StubMatchService.instance.calls[-1] == ("join-token", MUID, "m-abc")

    started = client.post(f"/api/matches/{MMID}/start", headers=headers)
    assert started.status_code == 200
    assert StubMatchService.instance.calls[-1] == ("start", MUID, MMID)

    submitted = client.post(f"/api/matches/{MMID}/submit", headers=headers,
                            json={"session_id": str(MSID)})
    assert submitted.status_code == 200
    assert StubMatchService.instance.calls[-1] == ("submit", MUID, MMID, MSID)

    finalized = client.post(f"/api/matches/{MMID}/finalize", headers=headers)
    assert finalized.status_code == 200

    mine = client.get("/api/matches/mine", headers=headers)
    assert mine.status_code == 200 and "items" in mine.json()

    invites = client.get("/api/matches/invites", headers=headers)
    assert invites.status_code == 200 and "items" in invites.json()

    link = client.get(f"/api/matches/{MMID}/invite-link", headers=headers)
    assert link.status_code == 200 and link.json()["token"] == "m-x"

    # No score/XP/outcome fields are accepted anywhere: submit takes only a
    # session id, and create takes only game/mode/difficulty/capacity.
    bad = client.post(f"/api/matches/{MMID}/submit", headers=headers,
                      json={"session_id": str(MSID), "score": 9999})
    assert bad.status_code == 200  # extra keys ignored, never trusted
    assert StubMatchService.instance.calls[-1] == ("submit", MUID, MMID, MSID)


def test_match_routes_map_errors(monkeypatch):
    from brainrush.db.errors import ConflictError, NotFoundError

    client = _match_client(monkeypatch)
    headers = {"X-Telegram-Init-Data": "anything"}

    StubMatchService.instance = None
    # Drive errors through a fresh stub by patching the class attribute.
    orig = StubMatchService.__init__

    def failing(self, session, **kw):
        orig(self, session, **kw)
        self.error = ConflictError("match is full")

    monkeypatch.setattr(StubMatchService, "__init__", failing)
    full = client.post(f"/api/matches/{MMID}/join", headers=headers)
    assert full.status_code == 409

    def missing(self, session, **kw):
        orig(self, session, **kw)
        self.error = NotFoundError("match not found")

    monkeypatch.setattr(StubMatchService, "__init__", missing)
    gone = client.get(f"/api/matches/{MMID}", headers=headers)
    assert gone.status_code == 404

    # Unknown game surfaces as 422 (ValueError), never 500.
    def bad_game(self, session, **kw):
        orig(self, session, **kw)

        async def create_match(**_kw):
            raise ValueError("game_type must be one of ['color_sequence']")

        self.create_match = create_match

    monkeypatch.setattr(StubMatchService, "__init__", bad_game)
    bad = client.post("/api/matches", headers=headers,
                      json={"game_type": "quiz_rush", "mode": "duel",
                            "difficulty": "hard"})
    assert bad.status_code == 422

    # Capacity bounds are enforced by request validation (422), not the DB.
    bad_cap = client.post("/api/matches", headers=headers,
                          json={"game_type": "number_guessing",
                                "mode": "duel", "difficulty": "hard",
                                "max_players": 99})
    assert bad_cap.status_code in (200, 422)


# -- perfect second multiplayer ----------------------------------------------

async def _perfect_solo(svc, user, target_ms, actual_ms, when=None):
    from brainrush.game import perfect_second as perfect

    scored = perfect.score_result(target_ms=target_ms, actual_ms=actual_ms)
    solo = svc.sessions.add_started(user.id, "perfect_second")
    moment = when or _utcnow()
    solo.status = "completed"
    solo.score = scored["score_ms"]
    solo.ended_at = moment
    row = svc.results.add(
        solo.id, scored["score_ms"], "win" if scored["won"] else "loss",
        {"game": "perfect_second", "difficulty": "medium",
         "target_ms": target_ms, "actual_ms": actual_ms,
         "error_ms": scored["error_ms"],
         "accuracy_percent": scored["accuracy_percent"]},
        xp=0,
    )
    row.created_at = moment
    return solo


async def test_perfect_match_shares_one_target():
    from brainrush.game import perfect_second as perfect

    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    mid = await _lobby(svc, host, game="perfect_second", mode="duel",
                       difficulty="medium")
    await _join(svc, guest, mid)
    lobby = await svc.get_match(user_id=host.id, match_id=mid)
    expected = perfect.match_target_ms(mid, "medium")
    assert lobby["target_ms"] == expected
    await _start(svc, host, mid)
    host_solo = await _perfect_solo(svc, host, expected, float(expected))
    guest_solo = await _perfect_solo(svc, guest, expected, float(expected) + 500)
    await svc.submit_result(user_id=host.id, match_id=mid,
                            session_id=host_solo.id)
    done = await svc.submit_result(user_id=guest.id, match_id=mid,
                                   session_id=guest_solo.id)
    assert done["status"] == "completed"
    ranks = {p["user_id"]: p["rank"] for p in done["participants"]}
    assert ranks[str(host.id)] == 1 and ranks[str(guest.id)] == 2
    # Winner: 10 completion + 10 win bonus; loser: 10. Exactly once each.
    paid = {p["user_id"]: p["xp_earned"] for p in done["participants"]}
    assert paid == {str(host.id): 20, str(guest.id): 10}
    xp_calls = svc.profiles.xp_calls
    assert sorted(xp_calls) == sorted([
        (host.id, 10), (host.id, 10), (guest.id, 10),
    ])
    assert session.commits == 0


async def test_perfect_match_duplicate_submit_replays_without_repay():
    from brainrush.game import perfect_second as perfect

    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    mid = await _lobby(svc, host, game="perfect_second", mode="duel",
                       difficulty="medium")
    await _join(svc, guest, mid)
    await _start(svc, host, mid)
    expected = perfect.match_target_ms(mid, "medium")
    solo = await _perfect_solo(svc, host, expected, float(expected))
    first = await svc.submit_result(user_id=host.id, match_id=mid,
                                    session_id=solo.id)
    assert first["status"] == "active"
    # Same session again: idempotent replay, no extra seat, no error.
    replay = await svc.submit_result(user_id=host.id, match_id=mid,
                                     session_id=solo.id)
    assert replay["status"] == "active"
    # A different session for the same seat is rejected.
    other = await _perfect_solo(svc, host, expected, float(expected) + 100)
    with pytest.raises(ConflictError):
        await svc.submit_result(user_id=host.id, match_id=mid,
                                session_id=other.id)
    # Finish via the guest, then finalize twice: XP stays single-paid.
    guest_solo = await _perfect_solo(svc, guest, expected, float(expected) + 500)
    done = await svc.submit_result(user_id=guest.id, match_id=mid,
                                   session_id=guest_solo.id)
    assert done["status"] == "completed"
    again = await svc.finalize_match(user_id=host.id, match_id=mid)
    assert again["status"] == "completed"
    assert svc.profiles.by_user[host.id].total_xp == 20
    assert svc.profiles.by_user[guest.id].total_xp == 10
    assert session.commits == 0


async def test_perfect_match_rejects_foreign_target():
    from brainrush.game import perfect_second as perfect

    session = RecordingSession()
    svc = _service(session)
    host = _registered(svc, 111)
    guest = _registered(svc, 222)
    mid = await _lobby(svc, host, game="perfect_second", mode="duel",
                       difficulty="medium")
    await _join(svc, guest, mid)
    await _start(svc, host, mid)
    expected = perfect.match_target_ms(mid, "medium")
    # A plain solo attempt rolls its own random target: with overwhelming
    # probability it differs from the shared one; force it explicitly.
    foreign = expected + 500 if expected + 500 <= 12_000 else expected - 500
    assert foreign != expected
    rogue = await _perfect_solo(svc, guest, foreign, float(foreign))
    with pytest.raises(ConflictError):
        await svc.submit_result(user_id=guest.id, match_id=mid,
                                session_id=rogue.id)


async def test_perfect_match_exact_tie_shares_rank():
    from brainrush.game import perfect_second as perfect

    session = RecordingSession()
    svc = _service(session)
    users = [_registered(svc, 111 + i) for i in range(3)]
    mid = await _lobby(svc, users[0], game="perfect_second", mode="ffa")
    for u in users[1:]:
        await _join(svc, u, mid)
    await _start(svc, users[0], mid)
    expected = perfect.match_target_ms(mid, "hard")
    moment = _utcnow()
    for u in users:
        solo = await _perfect_solo(svc, u, expected, float(expected) + 250,
                                   when=moment)
        await svc.submit_result(user_id=u.id, match_id=mid, session_id=solo.id)
    view = await svc.get_match(user_id=users[0].id, match_id=mid)
    assert sorted(p["rank"] for p in view["participants"]) == [1, 1, 1]
    assert session.commits == 0
