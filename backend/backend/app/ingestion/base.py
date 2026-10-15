"""Connector framework with source-health tracking (Sections 4, 51, 66.1, 66.13).

Every automated job runs through `run_source`, which records attempts,
successes, retries and errors. A failure raises an alert that points the user
to manual input, so missing data never blocks analysis."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Callable

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import SourceStatus
from app.db import utcnow
from app.models import Source, SourceHealth
from app.services.audit import alert

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 30
UA = {"User-Agent": "MacFundamentalIntelligence/1.0 (research platform)"}


class SourceUnavailable(RuntimeError):
    pass


def http_get(url: str, params: dict | None = None, retries: int = 2) -> requests.Response:
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=HTTP_TIMEOUT)
            if r.status_code >= 500:
                raise SourceUnavailable(f"{url} returned {r.status_code}")
            r.raise_for_status()
            return r
        except (requests.RequestException, SourceUnavailable) as exc:
            last = exc
    raise SourceUnavailable(str(last))


def _health(db: Session, key: str) -> tuple[Source, SourceHealth]:
    src = db.scalar(select(Source).where(Source.key == key))
    if src is None:
        raise LookupError(f"Unknown source {key}")
    h = db.scalar(select(SourceHealth).where(SourceHealth.source_id == src.id))
    if h is None:
        h = SourceHealth(source_id=src.id)
        db.add(h)
        db.flush()
    return src, h


def run_source(db: Session, key: str, fn: Callable[[Session, Source], int]) -> dict:
    """Run a connector function `fn(db, source) -> records` with health tracking."""
    src, h = _health(db, key)
    if not src.enabled:
        return {"source": key, "status": "disabled"}
    h.last_attempt_at = utcnow()
    db.commit()
    try:
        n = fn(db, src)
        src, h = _health(db, key)
        h.status = SourceStatus.OK.value
        h.last_success_at = utcnow()
        h.retries = 0
        h.last_error = None
        h.records_last_run = n
        h.expected_next_at = utcnow() + timedelta(minutes=src.freshness_minutes or 60)
        db.commit()
        return {"source": key, "status": "OK", "records": n}
    except Exception as exc:
        db.rollback()
        src, h = _health(db, key)
        h.status = SourceStatus.FAILED.value
        h.retries = (h.retries or 0) + 1
        h.last_error = f"{exc.__class__.__name__}: {exc}"[:1000]
        if h.retries == 1 or h.retries % 10 == 0:
            alert(db, "source_failure", f"{src.name}: data feed failed",
                  f"{h.last_error}. Retry {h.retries}. You can provide the latest data manually "
                  "(screenshot, PDF, typed or URL) from the Data Health page.", "MEDIUM",
                  entity="source", entity_id=src.id)
        db.commit()
        log.warning("source %s failed: %s", key, exc)
        return {"source": key, "status": "FAILED", "error": h.last_error, "retries": h.retries}
