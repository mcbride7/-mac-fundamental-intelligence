"""Send alerts to your phone through a Telegram bot.

Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID on the api and worker services. Every two minutes the
worker sends alerts that are HIGH severity or of a kind listed in TELEGRAM_ALERT_KINDS, at most
15 per run, and remembers what it sent so nothing goes twice. Alerts older than 6 hours are never
sent (no flood of old news on the first run)."""
from __future__ import annotations

import html
import logging
from datetime import timedelta

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import utcnow
from app.models import Alert
from app.models.notify import AlertDelivery

log = logging.getLogger(__name__)
MAX_PER_RUN = 15
MAX_AGE = timedelta(hours=6)
ICON = {"CRITICAL": "🔴", "HIGH": "🔴", "MEDIUM": "🟠", "LOW": "⚪"}


def configured() -> bool:
    return bool(settings.telegram_bot_token and settings.telegram_chat_id)


def wanted(a: Alert) -> bool:
    kinds = {k.strip() for k in (settings.telegram_alert_kinds or "").split(",") if k.strip()}
    return a.severity in ("HIGH", "CRITICAL") or "all" in kinds or a.kind in kinds


def format_alert(a: Alert) -> str:
    body = (a.body or "").strip()
    if len(body) > 600:
        body = body[:597] + "…"
    lines = [f"{ICON.get(a.severity, '•')} <b>{html.escape(a.title)}</b>"]
    if body:
        lines.append(html.escape(body))
    lines.append(f"<i>{html.escape(a.kind.replace('_', ' '))}</i>")
    if settings.public_url:
        lines.append(f'<a href="{html.escape(settings.public_url.rstrip("/"))}/alerts">Open alerts</a>')
    return "\n".join(lines)


def send_telegram(text: str) -> tuple[bool, str | None]:
    if not configured():
        return False, "Telegram is not set up (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)"
    try:
        r = requests.post(f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                          json={"chat_id": settings.telegram_chat_id, "text": text, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=15)
    except requests.RequestException as exc:
        return False, f"Could not reach Telegram ({exc.__class__.__name__})"
    if r.status_code != 200:
        try:
            desc = r.json().get("description", "")
        except ValueError:
            desc = r.text[:200]
        return False, f"Telegram said {r.status_code}: {desc}"
    return True, None


def send_pending(db: Session, now=None) -> dict:
    if not configured():
        return {"sent": 0, "skipped": "not configured"}
    now = now or utcnow()
    # sent or skipped alerts are finished; failed ones are retried on later runs (within MAX_AGE)
    done = select(AlertDelivery.alert_id).where(AlertDelivery.channel == "telegram",
                                                AlertDelivery.status.in_(("sent", "skipped")))
    q = (select(Alert).where(Alert.created_at >= now - MAX_AGE, Alert.id.not_in(done))
         .order_by(Alert.created_at))
    sent = failed = skipped = 0
    for a in db.scalars(q):
        if not wanted(a):
            db.add(AlertDelivery(alert_id=a.id, channel="telegram", status="skipped"))
            skipped += 1
            continue
        if sent + failed >= MAX_PER_RUN:
            break
        ok, err = send_telegram(format_alert(a))
        row = db.scalar(select(AlertDelivery).where(AlertDelivery.alert_id == a.id,
                                                    AlertDelivery.channel == "telegram"))
        if row is None:
            row = AlertDelivery(alert_id=a.id, channel="telegram")
            db.add(row)
        row.status, row.error, row.sent_at = ("sent" if ok else "failed"), err, utcnow()
        if ok:
            sent += 1
        else:
            failed += 1
            log.warning("Telegram alert %s failed: %s", a.id, err)
            if failed >= 3:  # Telegram down or settings wrong: stop and try again next run
                break
    db.commit()
    return {"sent": sent, "failed": failed, "skipped": skipped}


def status(db: Session) -> dict:
    last = db.scalar(select(AlertDelivery).where(AlertDelivery.channel == "telegram",
                                                 AlertDelivery.status != "skipped")
                     .order_by(AlertDelivery.sent_at.desc()))
    return {"configured": configured(), "kinds": settings.telegram_alert_kinds,
            "last_status": last.status if last else None, "last_error": last.error if last else None,
            "last_at": last.sent_at.isoformat() if last else None}
