"""Login sessions: a password check that hands out a signed, expiring session token.

The website no longer needs the API password built into its code. You type your password once on
the login page, the API returns a session token, and the browser keeps it. Tokens are signed with
HMAC-SHA256 and expire after SESSION_DAYS. Changing APP_PASSWORD (or SECRET_KEY) logs every
browser out."""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from collections import defaultdict, deque

from app.config import settings

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60
_failures: dict[str, deque] = defaultdict(deque)


def _key() -> bytes:
    base = settings.secret_key or f"{settings.api_token or ''}|{settings.app_password or ''}"
    return hashlib.sha256(("mfi-session|" + base).encode()).digest()


def _sign(payload: str) -> str:
    sig = hmac.new(_key(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def auth_enabled() -> bool:
    return bool(settings.api_token or settings.app_password)


def issue_session(now: float | None = None) -> tuple[str, int]:
    exp = int((now or time.time()) + settings.session_days * 86400)
    payload = f"s1.{exp}"
    return f"{payload}.{_sign(payload)}", exp


def session_valid(token: str, now: float | None = None) -> bool:
    try:
        ver, exp, sig = token.split(".")
    except ValueError:
        return False
    if ver != "s1" or not exp.isdigit():
        return False
    if not hmac.compare_digest(sig, _sign(f"{ver}.{exp}")):
        return False
    return int(exp) > (now or time.time())


def token_ok(bearer: str | None) -> bool:
    if not auth_enabled():
        return True
    if not bearer:
        return False
    if settings.api_token and hmac.compare_digest(bearer, settings.api_token):
        return True
    return session_valid(bearer)


def too_many_failures(client: str, now: float | None = None) -> bool:
    now = now or time.time()
    q = _failures[client]
    while q and now - q[0] > WINDOW_SECONDS:
        q.popleft()
    return len(q) >= MAX_FAILURES


def record_failure(client: str, now: float | None = None) -> None:
    _failures[client].append(now or time.time())


def check_password(password: str) -> bool:
    if not settings.app_password:
        return True
    return hmac.compare_digest(password.encode(), settings.app_password.encode())
