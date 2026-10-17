"""Shared API dependencies."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import Depends, Header, HTTPException
from sqlalchemy import inspect

from app.db import get_db  # noqa: F401  (re-export)


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Every request must send `Authorization: Bearer <token>`, where the token is either a login
    session (from /api/auth/login) or API_TOKEN itself (for scripts and the /docs page)."""
    from app.core.auth import token_ok

    bearer = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    if not token_ok(bearer):
        raise HTTPException(401, "Please log in")


def current_user_id(x_user_id: int | None = Header(default=None)) -> int:
    # Single-owner deployment by default; multi-user auth can replace this dependency.
    return x_user_id or 1


Auth = Depends(require_token)


def row(obj) -> dict | None:
    if obj is None:
        return None
    out = {}
    for c in inspect(obj).mapper.column_attrs:
        v = getattr(obj, c.key)
        out[c.key] = v.isoformat() if isinstance(v, (datetime, date)) else v
    return out


def rows(objs) -> list[dict]:
    return [row(o) for o in objs]


def not_found(what: str = "Not found"):
    raise HTTPException(404, what)
