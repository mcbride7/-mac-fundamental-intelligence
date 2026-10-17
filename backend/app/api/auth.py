"""Login (no token needed to call it)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import Auth
from app.core import auth

router = APIRouter(prefix="/api/auth", tags=["login"])


class LoginIn(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request):
    client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or \
        (request.client.host if request.client else "unknown")
    if auth.too_many_failures(client):
        raise HTTPException(429, "Too many wrong passwords. Wait 15 minutes and try again.")
    if not auth.check_password(body.password):
        auth.record_failure(client)
        raise HTTPException(401, "Wrong password")
    token, exp = auth.issue_session()
    return {"token": token, "expires_at": datetime.fromtimestamp(exp, timezone.utc).isoformat(),
            "auth_enabled": auth.auth_enabled()}


@router.get("/check", dependencies=[Auth])
def check():
    return {"ok": True}
