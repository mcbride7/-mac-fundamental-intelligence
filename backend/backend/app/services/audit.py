"""Audit log and alert helpers (Sections 47 and 66.15)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Alert, AuditLog


def audit(db: Session, entity: str, entity_id: int | None, action: str, user_id: int | None = None,
          **details) -> AuditLog:
    row = AuditLog(entity=entity, entity_id=entity_id, action=action, user_id=user_id, details=details)
    db.add(row)
    return row


def alert(db: Session, kind: str, title: str, body: str = "", severity: str = "MEDIUM", *,
          entity: str | None = None, entity_id: int | None = None, currency: str | None = None,
          central_bank_code: str | None = None, **data) -> Alert:
    row = Alert(kind=kind, title=title, body=body, severity=severity, entity=entity, entity_id=entity_id,
                currency=currency, central_bank_code=central_bank_code, data=data)
    db.add(row)
    return row
