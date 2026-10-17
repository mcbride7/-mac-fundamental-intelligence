import pytest


@pytest.fixture()
def locked(monkeypatch):
    from app.config import settings
    from app.core import auth

    monkeypatch.setattr(settings, "api_token", "script-token-123")
    monkeypatch.setattr(settings, "app_password", "my-login-pass")
    monkeypatch.setattr(settings, "secret_key", None)
    auth._failures.clear()
    yield
    auth._failures.clear()


def test_protected_without_login(client, locked):
    assert client.get("/api/sources").status_code == 401
    assert client.get("/health").status_code == 200  # uptime checks need no login


def test_login_gives_a_working_session(client, locked):
    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": "my-login-pass"})
    assert r.status_code == 200
    tok = r.json()["token"]
    assert client.get("/api/sources", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    assert client.get("/api/auth/check", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    # the script token still works
    assert client.get("/api/sources", headers={"Authorization": "Bearer script-token-123"}).status_code == 200
    # a tampered or expired token does not
    bad = tok[:-2] + ("AA" if not tok.endswith("AA") else "BB")
    assert client.get("/api/sources", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_expired_and_password_change(locked, monkeypatch):
    from app.config import settings
    from app.core import auth

    tok, exp = auth.issue_session(now=1_000_000)
    assert auth.session_valid(tok, now=1_000_100)
    assert not auth.session_valid(tok, now=exp + 1)
    tok2, _ = auth.issue_session()
    monkeypatch.setattr(settings, "app_password", "new-pass")
    assert not auth.session_valid(tok2)  # changing the password logs everyone out


def test_lockout_after_repeated_failures(client, locked):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"password": "my-login-pass"}).status_code == 429
