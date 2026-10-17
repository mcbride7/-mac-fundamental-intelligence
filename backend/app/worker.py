"""Celery worker and beat schedule (background jobs).

Run:
    celery -A app.worker worker --loglevel=info
    celery -A app.worker beat --loglevel=info
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.db import SessionLocal

celery_app = Celery("mfi", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(timezone="UTC", task_acks_late=True, worker_prefetch_multiplier=1)

celery_app.conf.beat_schedule = {
    "fred-every-6h": {"task": "app.worker.run_source_task", "schedule": crontab(minute=5, hour="*/6"),
                      "args": ["fred"]},
    "fed-rss-30m": {"task": "app.worker.run_source_task", "schedule": crontab(minute="*/30"), "args": ["fed_rss"]},
    "ecb-rss-30m": {"task": "app.worker.run_source_task", "schedule": crontab(minute="*/30"), "args": ["ecb_rss"]},
    "boe-rss-30m": {"task": "app.worker.run_source_task", "schedule": crontab(minute="*/30"), "args": ["boe_rss"]},
    "prices-hourly": {"task": "app.worker.run_source_task", "schedule": crontab(minute=2), "args": ["twelvedata"]},
    "calendar-hourly": {"task": "app.worker.run_source_task", "schedule": crontab(minute=10), "args": ["finnhub"]},
    "forexfactory-6h": {"task": "app.worker.run_source_task", "schedule": crontab(minute=20, hour="*/6"),
                        "args": ["forexfactory"]},
    "verify-pending-30m": {"task": "app.worker.verify_pending_task", "schedule": crontab(minute="*/30")},
    "missing-data-15m": {"task": "app.worker.missing_data_task", "schedule": crontab(minute="*/15")},
    "market-data-recompute-30m": {"task": "app.worker.recompute_entity_task", "schedule": crontab(minute="*/30"),
                                  "args": ["market_data"]},
    "track-record-hourly": {"task": "app.worker.track_record_task", "schedule": crontab(minute=40)},
    "full-recompute-nightly": {"task": "app.worker.recompute_entity_task", "schedule": crontab(minute=30, hour=2),
                               "args": ["full"]},
}


@celery_app.task(name="app.worker.recompute_task")
def recompute_task(job_id: int) -> dict:
    from app.services import recompute

    with SessionLocal() as db:
        return recompute.run_job(db, job_id).summary


@celery_app.task(name="app.worker.recompute_entity_task")
def recompute_entity_task(entity: str) -> dict:
    from app.services import recompute

    with SessionLocal() as db:
        job = recompute.create_job(db, entity, None)
        return recompute.run_job(db, job.id).summary


@celery_app.task(name="app.worker.run_source_task", autoretry_for=(), max_retries=0)
def run_source_task(key: str) -> dict:
    from app.ingestion.registry import run

    with SessionLocal() as db:
        res = run(db, key)
    if res.get("status") == "OK" and res.get("records"):
        recompute_entity_task.delay("market_data" if key == "twelvedata" else "full")
    return res


@celery_app.task(name="app.worker.verify_pending_task")
def verify_pending_task() -> dict:
    from app.services.verification_service import verify_pending

    with SessionLocal() as db:
        return verify_pending(db)


@celery_app.task(name="app.worker.missing_data_task")
def missing_data_task() -> int:
    """Prompt for manual input when a scheduled release has passed with no actual (66.1)."""
    from sqlalchemy import select

    from app.models import Alert
    from app.services.audit import alert
    from app.services.verification_service import missing_scheduled

    n = 0
    with SessionLocal() as db:
        for m in missing_scheduled(db):
            exists = db.scalar(select(Alert.id).where(Alert.kind == "missing_data", Alert.entity == "economic_event",
                                                      Alert.entity_id == m["event_id"]))
            if exists:
                continue
            alert(db, "missing_data", f"{m['indicator']} {m['reference_period']}: no actual received",
                  m["message"] + " Provide it as a screenshot, PDF, typed value or URL.", "HIGH",
                  entity="economic_event", entity_id=m["event_id"])
            n += 1
        db.commit()
    return n


@celery_app.task(name="app.worker.track_record_task")
def track_record_task() -> int:
    from app.services import track_record

    with SessionLocal() as db:
        return track_record.evaluate(db)
