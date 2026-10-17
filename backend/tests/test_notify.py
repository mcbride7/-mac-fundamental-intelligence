from datetime import timedelta

import pytest


@pytest.fixture()
def tg(monkeypatch):
    from app.config import settings
    from app.services import notify

    monkeypatch.setattr(settings, "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings, "telegram_chat_id", "42")
    monkeypatch.setattr(settings, "telegram_alert_kinds", "source_failure")
    sent = []
    monkeypatch.setattr(notify, "send_telegram", lambda text: (sent.append(text) or (True, None)))
    return sent


def _alert(db, kind, sev, title="t", age=timedelta(0)):
    from app.db import utcnow
    from app.models import Alert

    a = Alert(kind=kind, severity=sev, title=title, body="<b>x</b> & y", created_at=utcnow() - age)
    db.add(a)
    db.commit()
    return a


def test_sends_wanted_alerts_once(db, tg):
    from app.services import notify

    _alert(db, "high_conviction_setup", "HIGH", "EURUSD: grade A long setup")
    _alert(db, "source_failure", "MEDIUM", "FRED down")
    _alert(db, "yield_move", "MEDIUM", "2Y up 5bp")          # not wanted
    _alert(db, "policy_shift", "HIGH", "old", age=timedelta(hours=8))  # too old
    r = notify.send_pending(db)
    assert r["sent"] == 2 and r["skipped"] == 1
    assert "EURUSD" in tg[0] and "&lt;b&gt;x&lt;/b&gt; &amp; y" in tg[0]  # escaped for Telegram HTML
    assert notify.send_pending(db)["sent"] == 0  # never twice


def test_not_configured(db, monkeypatch):
    from app.config import settings
    from app.services import notify

    monkeypatch.setattr(settings, "telegram_bot_token", None)
    assert notify.send_pending(db) == {"sent": 0, "skipped": "not configured"}
    assert notify.status(db)["configured"] is False


def test_failures_stop_early(db, monkeypatch, tg):
    from app.services import notify

    monkeypatch.setattr(notify, "send_telegram", lambda text: (False, "Telegram said 401: Unauthorized"))
    for i in range(5):
        _alert(db, "source_failure", "HIGH", f"a{i}")
    r = notify.send_pending(db)
    assert r["failed"] == 3 and notify.status(db)["last_error"].startswith("Telegram said 401")
    # once Telegram works again, the failed ones are retried
    monkeypatch.setattr(notify, "send_telegram", lambda text: (True, None))
    assert notify.send_pending(db)["sent"] == 5


def test_test_endpoint_reports_setup_problem(client):
    r = client.post("/api/notifications/test")
    assert r.status_code == 400 and "not set up" in r.json()["detail"]
