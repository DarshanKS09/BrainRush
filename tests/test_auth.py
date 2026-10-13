"""initData auth + progression math. No network, no DB."""
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from brainrush.api.auth import AuthError, parse_and_verify
from brainrush.game.progression import (
    level_for_xp,
    progress_for_xp,
    xp_to_reach,
)

TOKEN = "test-bot-token-12345"


def _sign(params: dict) -> str:
    data_check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


def _init_data(user_id=777, username="carol", extra=None, age=60):
    user = {"id": user_id, "first_name": "Carol", "last_name": "D",
            "username": username}
    params = {"query_id": "abc", "user": json.dumps(user, separators=(",", ":")),
              "auth_date": str(int(time.time()) - age)}
    if extra:
        params.update(extra)
    params["hash"] = _sign(params)
    return urlencode(params)


def _verify(data, **kw):
    return parse_and_verify(data, bot_token=TOKEN, max_age_seconds=3600, **kw)


def test_valid_init_data_derives_user():
    ident = _verify(_init_data())
    assert ident == {"telegram_id": 777, "username": "carol",
                     "display_name": "Carol D"}


def test_tampered_user_id_breaks_signature():
    data = _init_data(user_id=777)
    tampered = data.replace("%22id%22%3A777", "%22id%22%3A778")
    # sanity: replacement actually changed something encodable differently
    if tampered == data:
        tampered += "&x=1"
    with pytest.raises(AuthError):
        _verify(tampered)


def test_wrong_token_rejected():
    data = _init_data()
    with pytest.raises(AuthError):
        parse_and_verify(data, bot_token="other-token", max_age_seconds=3600)


def test_expired_rejected():
    with pytest.raises(AuthError) as exc:
        _verify(_init_data(age=7200))
    assert "expired" in str(exc.value)


def test_missing_and_malformed_rejected():
    for bad in ("", "   ", "foo=bar", "user=%7B%7D&auth_date=1"):
        with pytest.raises(AuthError):
            _verify(bad)


def test_user_id_never_trusted_from_elsewhere():
    # display fields are cosmetic; identity key is the signed id only
    ident = _verify(_init_data(user_id=5, username="mallory"))
    assert ident["telegram_id"] == 5


def test_dev_bypass_gated():
    with pytest.raises(AuthError):
        _verify("dev")
    ident = _verify("dev", allow_dev=True, dev_telegram_id=42)
    assert ident["telegram_id"] == 42
    with pytest.raises(AuthError):
        _verify("dev", allow_dev=True, dev_telegram_id=0)


def test_progression_thresholds():
    assert [xp_to_reach(n) for n in (1, 2, 3, 4, 5)] == [0, 100, 300, 600, 1000]
    assert level_for_xp(0) == 1
    assert level_for_xp(99) == 1
    assert level_for_xp(100) == 2
    assert level_for_xp(299) == 2
    assert level_for_xp(300) == 3
    assert progress_for_xp(150) == {"level": 2, "xp_into_level": 50,
                                    "xp_for_next": 200}
    with pytest.raises(ValueError):
        xp_to_reach(0)
    with pytest.raises(ValueError):
        level_for_xp(-1)
