"""API route tests: TestClient + stubbed service layer. No real DB/Telegram."""
import uuid

from fastapi import Request
from fastapi.testclient import TestClient

from brainrush.api import routes
from brainrush.api.app import create_app
from brainrush.api.deps import get_session, get_verified_identity
from brainrush.config import Settings


def _settings(**kw):
    base = dict(
        BOT_TOKEN="test-token",
        DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db",
    )
    base.update(kw)
    return Settings(**base)


class StubService:
    """Stands in for MiniappGameService; handlers construct per request."""

    instance = None

    def __init__(self, session):
        self.calls = []
        self.dashboard_data = {"user": {}, "profile": {}}
        self.state_data = {"finished": False}
        self.finish_data = {"finished": True, "result": {"xp_earned": 10}}
        self.history_data = []
        self.leaderboard_data = {"entries": [], "my_rank": 1}
        self.error = None
        StubService.instance = self

    def _raise(self):
        if self.error is not None:
            raise self.error

    async def dashboard(self, *, user_id):
        self.calls.append(("dashboard", user_id))
        self._raise()
        return self.dashboard_data

    async def start_game(self, *, user_id, difficulty="hard"):
        self.calls.append(("start", user_id, difficulty))
        self._raise()
        return self.state_data

    async def get_state(self, *, session_id, user_id):
        self.calls.append(("state", session_id, user_id))
        self._raise()
        return self.state_data

    async def guess(self, *, session_id, user_id, value, client_guess_id):
        self.calls.append(("guess", session_id, user_id, value, client_guess_id))
        self._raise()
        return self.finish_data

    async def cancel(self, *, session_id, user_id):
        self.calls.append(("cancel", session_id, user_id))
        self._raise()
        return {"session_id": str(session_id), "status": "abandoned"}

    async def history(self, *, user_id, limit=20, offset=0):
        self.calls.append(("history", user_id, limit, offset))
        self._raise()
        return self.history_data

    async def leaderboard(self, *, limit=20, offset=0, user_id=None):
        self.calls.append(("leaderboard", limit, offset, user_id))
        self._raise()
        return self.leaderboard_data


UID = uuid.uuid4()
SID = uuid.uuid4()


def _client(monkeypatch, **settings_kw):
    app = create_app(_settings(**settings_kw),
                     session_factory=_dummy_factory())

    async def fake_session(request: Request):
        yield object()

    async def fake_identity(request: Request):
        request.state.telegram_id = 777
        return {"user_id": UID, "telegram_id": 777,
                "username": "carol", "display_name": "Carol D"}

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_verified_identity] = fake_identity
    monkeypatch.setattr(routes, "MiniappGameService", StubService)
    return TestClient(app, raise_server_exceptions=False)


class _DummyCM:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *exc):
        return False


def _dummy_factory():
    return _DummyCM()


def _auth_client(monkeypatch):
    """Real auth path; working dummy session factory."""
    from brainrush.api.deps import get_session as _gs

    app = create_app(_settings(), session_factory=_dummy_factory())

    async def fake_session(request: Request):
        yield object()

    app.dependency_overrides[_gs] = fake_session
    monkeypatch.setattr(routes, "MiniappGameService", StubService)
    return TestClient(app, raise_server_exceptions=False)


def _no_secret(obj) -> bool:
    if isinstance(obj, dict):
        return "secret" not in obj and all(_no_secret(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_no_secret(v) for v in obj)
    return True


def test_health_no_auth_needed(monkeypatch):
    client = _client(monkeypatch)
    assert client.get("/health").json() == {"status": "ok"}


def test_unauthenticated_rejected(monkeypatch):
    client = _auth_client(monkeypatch)
    # No X-Telegram-Init-Data header at all -> 401 (or 422 from missing header
    # mapped by FastAPI; either way, never 200).
    response = client.get("/api/me")
    assert response.status_code in (401, 422)


def test_bad_token_rejected(monkeypatch):
    client = _auth_client(monkeypatch)
    response = client.get("/api/me", headers={"X-Telegram-Init-Data": "bogus"})
    assert response.status_code == 401


def test_dashboard_games_history_leaderboard(monkeypatch):
    client = _client(monkeypatch)
    headers = {"X-Telegram-Init-Data": "anything"}

    me = client.get("/api/me", headers=headers)
    assert me.status_code == 200 and "profile" in me.json()

    games = client.get("/api/games", headers=headers)
    body = games.json()
    assert games.status_code == 200
    by_id = {g["id"]: g for g in body["games"]}
    assert by_id["number_guessing"]["playable"] is True
    assert by_id["memory_match"]["playable"] is False
    diffs = {d["id"]: d["max_attempts"]
             for d in by_id["number_guessing"]["difficulties"]}
    assert diffs == {"easy": 15, "medium": 10, "hard": 7}

    hist = client.get("/api/history", headers=headers)
    assert hist.status_code == 200 and "items" in hist.json()

    lb = client.get("/api/leaderboard", headers=headers)
    assert lb.status_code == 200 and "entries" in lb.json()


def test_game_lifecycle_hides_secret(monkeypatch):
    client = _client(monkeypatch)
    headers = {"X-Telegram-Init-Data": "anything"}

    started = client.post("/api/sessions", headers=headers,
                          json={"game_type": "number_guessing",
                                "difficulty": "medium"})
    assert started.status_code == 200
    assert _no_secret(started.json())

    state = client.get(f"/api/sessions/{SID}", headers=headers)
    assert state.status_code == 200
    assert _no_secret(state.json())

    done = client.post(f"/api/sessions/{SID}/guess", headers=headers,
                       json={"value": 42, "client_guess_id": "g1"})
    assert done.status_code == 200

    cancelled = client.delete(f"/api/sessions/{SID}", headers=headers)
    assert cancelled.status_code == 200


def test_unplayable_game_rejected(monkeypatch):
    client = _client(monkeypatch)
    response = client.post("/api/sessions",
                           headers={"X-Telegram-Init-Data": "x"},
                           json={"game_type": "memory_match", "difficulty": "easy"})
    assert response.status_code == 400


def test_service_errors_map_to_status_codes(monkeypatch):
    from brainrush.db.errors import ConflictError, NotFoundError

    client = _client(monkeypatch)
    headers = {"X-Telegram-Init-Data": "x"}

    StubService.instance = None
    # Force the next constructed stub to fail: patch constructor wrapper
    original = StubService.__init__

    def failing_init(self, session):
        original(self, session)
        self.error = NotFoundError("gone")

    monkeypatch.setattr(StubService, "__init__", failing_init)
    assert client.get(f"/api/sessions/{SID}", headers=headers).status_code == 404

    def conflict_init(self, session):
        original(self, session)
        self.error = ConflictError("done")

    monkeypatch.setattr(StubService, "__init__", conflict_init)
    assert client.post(f"/api/sessions/{SID}/guess", headers=headers,
                       json={"value": 1, "client_guess_id": "c"}).status_code == 409

    def value_init(self, session):
        original(self, session)
        self.error = ValueError("bad difficulty")

    monkeypatch.setattr(StubService, "__init__", value_init)
    assert client.post("/api/sessions", headers=headers,
                       json={"difficulty": "extreme"}).status_code == 422
