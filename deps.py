"""Shared API dependencies."""
from __future__ import annotations

from datetime import date, datetime

from fastapi import Depends, Header, HTTPException
from sqlalchemy import inspect

from app.config import settings
from app.db import get_db  # noqa: F401  (re-export)


def require_token(authorization: str | None = Header(default=None)) -> None:
    """If API_TOKEN is set, every request must send `Authorization: Bearer <token>`."""
    if not settings.api_token:
        return
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(401, "Invalid or missing API token")


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
