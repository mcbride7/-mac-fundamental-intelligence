"""Verification, data health, reconciliation, trust settings and sources (Section 66)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Auth, current_user_id, get_db, row, rows
from app.core.verification import badge
from app.models import (
    AuditLog,
    DataConfirmation,
    DataReconciliation,
    EconomicRelease,
    Indicator,
    Source,
    UserTrustSettings,
    VerificationAttempt,
)
from app.services import verification_service as vs

router = APIRouter(prefix="/api", tags=["verification & data health"], dependencies=[Auth])


class ConfirmIn(BaseModel):
    basis: str  # OFFICIAL_SOURCE | SECONDARY_SOURCE | NO_SOURCE
    source_name: str | None = None
    source_url: str | None = None
    evidence_file_id: int | None = None
    note: str | None = None


class ResolveIn(BaseModel):
    resolution: str  # use_official | keep_manual


class TrustIn(BaseModel):
    auto_confirm_typed: bool | None = None
    auto_confirm_official_screenshots: bool | None = None
    auto_confirm_threshold: float | None = None
    trusted_sources: list[str] | None = None


@router.post("/data/{release_id}/confirm")
def confirm(release_id: int, body: ConfirmIn, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    try:
        return vs.confirm_release(db, release_id, body.basis, user_id, body.source_name, body.source_url,
                                  body.evidence_file_id, body.note)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/data/{release_id}/unconfirm")
def unconfirm(release_id: int, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    try:
        return vs.unconfirm_release(db, release_id, user_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get("/data/{release_id}")
def get_release(release_id: int, db: Session = Depends(get_db)):
    r = db.get(EconomicRelease, release_id)
    if r is None:
        raise HTTPException(404, "Release not found")
    ind = db.get(Indicator, r.indicator_id)
    conf = db.scalar(select(DataConfirmation).where(DataConfirmation.release_id == r.id,
                                                    DataConfirmation.revoked.is_(False))
                     .order_by(DataConfirmation.created_at.desc()))
    return {**row(r), "indicator": ind.code, "indicator_name": ind.name,
            "badge": badge(r.verification_status, r.confirmation_basis, conf.source_name if conf else None),
            "confirmation": row(conf)}


@router.get("/data/{release_id}/audit")
def audit_log(release_id: int, db: Session = Depends(get_db)):
    return rows(db.scalars(select(AuditLog).where(AuditLog.entity == "economic_release",
                                                  AuditLog.entity_id == release_id).order_by(AuditLog.created_at)))


@router.get("/data/{release_id}/verification-attempts")
def attempts(release_id: int, db: Session = Depends(get_db)):
    return rows(db.scalars(select(VerificationAttempt).where(VerificationAttempt.release_id == release_id)
                           .order_by(VerificationAttempt.attempted_at.desc())))


@router.get("/data-health")
def data_health(db: Session = Depends(get_db)):
    h = vs.data_health(db)
    pending = []
    for r in vs.pending_verification(db):
        if not r.is_current:
            continue
        ind = db.get(Indicator, r.indicator_id)
        last = db.scalar(select(VerificationAttempt).where(VerificationAttempt.release_id == r.id)
                         .order_by(VerificationAttempt.attempted_at.desc()))
        pending.append({"release_id": r.id, "indicator": ind.code, "name": ind.name, "period": r.reference_period,
                        "actual": r.actual, "status": r.verification_status,
                        "badge": badge(r.verification_status, r.confirmation_basis), "input_method": r.input_method,
                        "last_attempt": row(last), "can_confirm": r.verification_status == "UNVERIFIED"})
    h["pending_verification"] = pending
    return h


@router.post("/data-health/verify-now")
def verify_now(db: Session = Depends(get_db)):
    return vs.verify_pending(db)


@router.get("/reconciliation")
def reconciliation(resolved: bool | None = False, db: Session = Depends(get_db)):
    q = select(DataReconciliation).order_by(DataReconciliation.created_at.desc())
    if resolved is not None:
        q = q.where(DataReconciliation.resolved.is_(resolved))
    out = []
    for rec in db.scalars(q):
        man = db.get(EconomicRelease, rec.release_id)
        ind = db.get(Indicator, man.indicator_id)
        out.append({**row(rec), "indicator": ind.code, "name": ind.name, "period": man.reference_period})
    return out


@router.post("/reconciliation/{rec_id}/resolve")
def resolve(rec_id: int, body: ResolveIn, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    try:
        return vs.resolve_conflict(db, rec_id, body.resolution, user_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.get("/settings/trust")
def get_trust(db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    t = db.get(UserTrustSettings, user_id)
    if t is None:
        t = UserTrustSettings(user_id=user_id)
        db.add(t)
        db.commit()
    return row(t)


@router.put("/settings/trust")
def put_trust(body: TrustIn, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    t = db.get(UserTrustSettings, user_id) or UserTrustSettings(user_id=user_id)
    db.add(t)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(t, k, v)
    db.commit()
    return row(t)


@router.get("/sources")
def sources(db: Session = Depends(get_db)):
    return rows(db.scalars(select(Source).order_by(Source.tier, Source.key)))


@router.post("/sources/{key}/run")
def run_source(key: str, db: Session = Depends(get_db)):
    from app.ingestion.registry import JOBS, run

    if key not in JOBS:
        raise HTTPException(404, f"No automated job for source '{key}'")
    res = run(db, key)
    if res.get("status") == "OK" and res.get("records"):
        from app.services import recompute

        job = recompute.trigger(db, "market_data" if key == "twelvedata" else "full", None)
        res["recompute"] = job.summary
    return res
