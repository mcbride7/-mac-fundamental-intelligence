"""Monitoring and backups.

- `deep_health` is what an outside uptime monitor (e.g. UptimeRobot) should check: it fails (503)
  when the database is unreachable or the worker hasn't checked in for 20 minutes, so you hear
  about it even if the website itself still loads.
- `export_all` dumps every table to one gzip JSON file you can download and keep off Railway,
  on top of Railway's own volume backups."""
from __future__ import annotations

import gzip
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import Base, utcnow
from app.models.notify import Heartbeat

WORKER_STALE = timedelta(minutes=20)


def beat(db: Session, name: str = "worker") -> None:
    hb = db.get(Heartbeat, name) or Heartbeat(name=name)
    hb.last_seen = utcnow()
    db.add(hb)
    db.commit()


def deep_health(db: Session) -> tuple[bool, dict]:
    out: dict = {"database": "ok"}
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        return False, {"database": f"down ({exc.__class__.__name__})"}
    hb = db.get(Heartbeat, "worker")
    now = utcnow()
    if hb is None:
        out["worker"] = "never seen"
        worker_ok = False
    else:
        seen = hb.last_seen if hb.last_seen.tzinfo else hb.last_seen.replace(tzinfo=timezone.utc)
        mins = round((now - seen).total_seconds() / 60, 1)
        worker_ok = now - seen <= WORKER_STALE
        out["worker"] = f"ok (checked in {mins} min ago)" if worker_ok else f"silent for {mins} min"
    from app.services.verification_service import data_health

    h = data_health(db)
    failing = [s["key"] for s in h["sources"] if s["status"] in ("FAILED", "STALE") and s.get("runnable")]
    out["failing_feeds"] = failing
    out["status"] = "ok" if worker_ok else "degraded"
    return worker_ok, out


def _json(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bytes):
        return None
    return v


def export_all(db: Session) -> bytes:
    tables = {}
    for name, table in Base.metadata.tables.items():
        rows = db.execute(select(table)).mappings().all()
        tables[name] = [{k: _json(v) for k, v in r.items()} for r in rows]
    payload = {"exported_at": utcnow().isoformat(), "format": "mfi-export-1", "tables": tables}
    return gzip.compress(json.dumps(payload, default=str).encode())
