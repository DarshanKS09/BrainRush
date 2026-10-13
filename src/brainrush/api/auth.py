"""Telegram Mini App initData verification (official algorithm, stdlib only).

Flow: Telegram signs the WebApp query params with HMAC-SHA256 keyed by the
bot token; the backend recomputes the signature and compares in constant
time. The Telegram user id is derived from the *verified* payload, never
from a frontend-supplied id.

Development bypass: the literal initData value "dev" is accepted ONLY when
settings explicitly enable it (ALLOW_DEV_AUTH + DEV_AUTH_TELEGRAM_ID). It is
refused otherwise, and startup logs a loud warning while enabled.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class AuthError(Exception):
    """initData missing, malformed, expired, or badly signed."""


def parse_and_verify(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int,
    now: float | None = None,
    allow_dev: bool = False,
    dev_telegram_id: int = 0,
) -> dict:
    """Return {telegram_id, username, display_name} or raise AuthError."""
    if not init_data or not init_data.strip():
        raise AuthError("missing authentication data")
    init_data = init_data.strip()

    if init_data == "dev":
        if allow_dev and dev_telegram_id:
            return {
                "telegram_id": dev_telegram_id,
                "username": "devplayer",
                "display_name": "Dev Player",
            }
        raise AuthError("invalid authentication data")

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        raise AuthError("malformed authentication data") from None
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise AuthError("malformed authentication data")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise AuthError("invalid signature")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError:
        raise AuthError("malformed authentication data") from None
    moment = now if now is not None else time.time()
    if auth_date <= 0 or moment - auth_date > max_age_seconds:
        raise AuthError("authentication data expired")

    try:
        raw_user = json.loads(pairs.get("user", "{}"))
        telegram_id = int(raw_user["id"])
    except (ValueError, KeyError, TypeError):
        raise AuthError("malformed user data") from None
    if telegram_id == 0:
        raise AuthError("malformed user data")

    username = raw_user.get("username") or None
    first = (raw_user.get("first_name") or "").strip()
    last = (raw_user.get("last_name") or "").strip()
    display = f"{first} {last}".strip() or f"Player {telegram_id}"
    return {"telegram_id": telegram_id, "username": username, "display_name": display}
