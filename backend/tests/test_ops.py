import gzip
import json
from datetime import timedelta


def test_deep_health_needs_a_live_worker(client, db):
    from app.db import utcnow
    from app.models.notify import Heartbeat
    from app.services import ops

    r = client.get("/health/deep")
    assert r.status_code == 503 and r.json()["worker"] == "never seen" and r.json()["database"] == "ok"
    ops.beat(db)
    r = client.get("/health/deep")
    assert r.status_code == 200 and r.json()["worker"].startswith("ok")
    db.get(Heartbeat, "worker").last_seen = utcnow() - timedelta(minutes=45)
    db.commit()
    assert client.get("/health/deep").status_code == 503


def test_backup_export_contains_every_table(client):
    r = client.get("/api/backup/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    data = json.loads(gzip.decompress(r.content))
    assert data["format"] == "mfi-export-1"
    assert "economic_releases" in data["tables"] and "signal_records" in data["tables"]
    assert len(data["tables"]["economic_indicators"]) >= 40
