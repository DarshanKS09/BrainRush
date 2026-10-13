"""Transaction-boundary regression tests (no real DB).

Reproduces the live `/play` failure:
`InvalidRequestError: A transaction is already begun on this Session.`

Cause: a repository SELECT ran outside any `session.begin()` block, and
SQLAlchemy autobegins a transaction on first use. The next service-owned
`begin()` on that same per-update session then blew up.

`StrictSession` emulates exactly that autobegin rule using the real
`sqlalchemy.exc.InvalidRequestError`, so the old call pattern fails here the
same way it failed live, and the fixed service methods succeed.
"""
import uuid

import pytest
from sqlalchemy.exc import InvalidRequestError

from brainrush.db.models import GameSession, PlayerProfile, User
from brainrush.db.repository import GameSessionRepository
from brainrush.services.games import GameSessionService
from brainrush.services.profiles import ProfileService
from brainrush.services.users import UserService
from tests.test_repositories import FakeResult, RecordingSession


class _StrictTx:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        if self.session._in_txn:
            raise InvalidRequestError(
                "A transaction is already begun on this Session."
            )
        self.session._in_txn = True
        self.session.begun += 1
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        self.session._in_txn = False
        if exc_type is None:
            self.session.tx_committed += 1
        else:
            self.session.rollbacks += 1
        return False


class StrictSession(RecordingSession):
    """RecordingSession + SQLAlchemy autobegin semantics."""

    def __init__(self, script=()):
        super().__init__(script)
        self._in_txn = False

    async def execute(self, stmt, *args, **kwargs):
        self._in_txn = True  # autobegin on first use
        return await super().execute(stmt, *args, **kwargs)

    async def get(self, model, pk):
        self._in_txn = True  # autobegin on first use
        return await super().get(model, pk)

    def begin(self):
        if self._in_txn:
            raise InvalidRequestError(
                "A transaction is already begun on this Session."
            )
        return _StrictTx(self)


def _user():
    user = User(telegram_id=4242, username="strict", display_name="Strict")
    user.id = uuid.uuid4()
    return user


def _started_row(user_id):
    row = GameSession(user_id=user_id, game_type="number_guessing", status="started")
    row.id = uuid.uuid4()
    return row


async def test_old_pattern_raw_select_then_begin_raises():
    """Locks in the diagnosis: bare repo SELECT poisons the session."""
    stale = _started_row(uuid.uuid4())
    session = StrictSession(script=[FakeResult(rows=[stale])])

    await GameSessionRepository(session).list_by_user(
        user_id=stale.user_id, status="started"
    )
    with pytest.raises(InvalidRequestError):
        await GameSessionService(session).start_session(
            user_id=stale.user_id, game_type="number_guessing"
        )


async def test_abandon_stale_sessions_owns_one_transaction():
    user = _user()
    stale = _started_row(user.id)
    done = _started_row(user.id)
    done.status = "abandoned"
    session = StrictSession(
        script=[
            FakeResult(rows=[stale]),  # list started
            stale,  # abandon: get
            FakeResult(rowcount=1),  # abandon: update
            done,  # abandon: re-get
        ]
    )

    abandoned = await GameSessionService(session).abandon_stale_sessions(
        user_id=user.id
    )

    assert [r.status for r in abandoned] == ["abandoned"]
    assert session.begun == 1 and session.tx_committed == 1
    assert session.commits == 0


async def test_full_play_sequence_on_one_session_succeeds():
    """The exact live /play order on a single session: register, sweep stale,
    start. Previously raised InvalidRequestError at start_session."""
    user = _user()
    profile = PlayerProfile(
        user_id=user.id, total_xp=0, current_level=1, games_played=0,
        wins=0, losses=0, current_streak=0, longest_streak=0,
    )
    stale = _started_row(user.id)
    stale_done = _started_row(user.id)
    stale_done.status = "abandoned"
    session = StrictSession(
        script=[
            FakeResult(rows=[]),  # users: select (absent)
            FakeResult(rowcount=1),  # users: upsert
            FakeResult(rows=[user]),  # users: re-select
            FakeResult(rows=[]),  # profiles: select (absent)
            FakeResult(rowcount=1),  # profiles: upsert
            FakeResult(rows=[profile]),  # profiles: re-select
            FakeResult(rows=[stale]),  # stale sweep: list
            stale,  # stale sweep: abandon get
            FakeResult(rowcount=1),  # stale sweep: abandon update
            FakeResult(rows=[stale_done]),  # stale sweep: abandon re-get
            user,  # start_session: user check
        ]
    )

    registered, _ = await UserService(session).get_or_register(
        telegram_id=user.telegram_id
    )
    abandoned = await GameSessionService(session).abandon_stale_sessions(
        user_id=registered.id
    )
    started = await GameSessionService(session).start_session(
        user_id=registered.id, game_type="number_guessing"
    )

    assert registered.telegram_id == 4242
    assert len(abandoned) == 1
    assert started is not None and started.status == "started"
    assert session.begun == 3 and session.tx_committed == 3
    assert session.commits == 0


async def test_get_stats_leaves_no_open_transaction():
    profile = PlayerProfile(
        user_id=uuid.uuid4(), total_xp=10, current_level=1, games_played=1,
        wins=1, losses=0, current_streak=1, longest_streak=1,
    )
    session = StrictSession(
        script=[FakeResult(rows=[profile]), FakeResult(rows=[profile])]
    )
    svc = ProfileService(session)

    first = await svc.get_stats(user_id=profile.user_id)
    second = await svc.get_stats(user_id=profile.user_id)

    assert first is profile and second is profile
    assert session.begun == 2 and session.tx_committed == 2
