"""User confirmation, background verification and reconciliation (Sections 66.9-66.12)."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.enums import ConfirmationBasis, SourceStatus, VerificationStatus
from app.core.verification import badge
from app.db import utcnow
from app.models import (
    DataConfirmation,
    DataReconciliation,
    EconomicRelease,
    Indicator,
    Source,
    SourceHealth,
    VerificationAttempt,
)
from app.services.audit import alert, audit

log = logging.getLogger(__name__)

# fetch_official(indicator, period) -> float | None ; raises on network failure
OfficialFetcher = Callable[[Indicator, str], "float | None"]


def _ctx_for(db: Session, rel: EconomicRelease) -> dict:
    ind = db.get(Indicator, rel.indicator_id)
    ctx = defaultdict(set)
    ctx["release_ids"].add(rel.id)
    ctx["indicator_ids"].add(ind.id)
    ctx["currencies"].add(ind.currency)
    if ind.central_bank_code:
        ctx["central_banks"].add(ind.central_bank_code)
    return ctx


def confirm_release(db: Session, release_id: int, basis: str, user_id: int | None = None,
                    source_name: str | None = None, source_url: str | None = None,
                    evidence_file_id: int | None = None, note: str | None = None,
                    run_recompute: bool = True) -> dict:
    from app.services import recompute

    rel = db.get(EconomicRelease, release_id)
    if rel is None:
        raise LookupError("Release not found")
    ConfirmationBasis(basis)  # validate
    if rel.verification_status == VerificationStatus.VERIFIED.value:
        raise ValueError("Already verified against the official source — no confirmation needed")
    if rel.verification_status == VerificationStatus.SUPERSEDED.value:
        raise ValueError("This value has been superseded")
    if basis == ConfirmationBasis.SECONDARY_SOURCE.value and not source_name:
        raise ValueError("Name the secondary source you confirmed against")
    was = rel.verification_status
    if was == VerificationStatus.CONFLICT.value:
        raise ValueError("This value conflicts with the official source — resolve the conflict instead")
    rel.verification_status = VerificationStatus.USER_CONFIRMED.value
    rel.confirmation_basis = basis
    conf = DataConfirmation(release_id=rel.id, user_id=user_id, basis=basis, source_name=source_name,
                            source_url=source_url, evidence_file_id=evidence_file_id, note=note)
    db.add(conf)
    audit(db, "economic_release", rel.id, "user_confirmed", user_id, basis=basis, source_name=source_name,
          source_url=source_url, previous_status=was)
    db.commit()
    out = {"release_id": rel.id, "status": rel.verification_status,
           "badge": badge(rel.verification_status, basis, source_name)}
    if run_recompute:
        job = recompute.trigger(db, "release", rel.id, **_ctx_for(db, rel))
        out["recompute"] = job.summary
    return out


def unconfirm_release(db: Session, release_id: int, user_id: int | None = None) -> dict:
    from app.services import recompute

    rel = db.get(EconomicRelease, release_id)
    if rel is None:
        raise LookupError("Release not found")
    if rel.verification_status != VerificationStatus.USER_CONFIRMED.value:
        raise ValueError("Only user-confirmed values can be un-confirmed")
    rel.verification_status = VerificationStatus.UNVERIFIED.value
    rel.confirmation_basis = None
    for c in db.scalars(select(DataConfirmation).where(DataConfirmation.release_id == rel.id,
                                                       DataConfirmation.revoked.is_(False))):
        c.revoked = True
    audit(db, "economic_release", rel.id, "user_unconfirmed", user_id)
    db.commit()
    job = recompute.trigger(db, "release", rel.id, **_ctx_for(db, rel))
    return {"release_id": rel.id, "status": rel.verification_status, "recompute": job.summary}


def reconcile(db: Session, rel: EconomicRelease, official_value: float, source_key: str,
              source_name: str | None = None) -> str:
    """Compare a manual value with the official value once the source is reachable.
    Returns outcome: match | mismatch."""
    tol = settings.verification_tolerance
    ind = db.get(Indicator, rel.indicator_id)
    if abs(official_value - rel.actual) <= tol:
        prior = rel.verification_status
        rel.verification_status = VerificationStatus.VERIFIED.value
        db.add(VerificationAttempt(release_id=rel.id, source_key=source_key, outcome="match",
                                   official_value=official_value))
        audit(db, "economic_release", rel.id, "verified", None, source=source_key, prior_status=prior)
        return "match"
    prior = rel.verification_status
    official = EconomicRelease(
        event_id=rel.event_id, indicator_id=rel.indicator_id, reference_period=rel.reference_period,
        actual=official_value, previous=rel.previous, consensus=rel.consensus, unit=rel.unit,
        released_at=rel.released_at, revision_number=rel.revision_number, source_name=source_name or source_key,
        input_method="automated", verification_status=VerificationStatus.VERIFIED.value, is_current=False,
    )
    src = db.scalar(select(Source).where(Source.key == source_key))
    official.source_id = src.id if src else None
    db.add(official)
    db.flush()
    rel.verification_status = VerificationStatus.CONFLICT.value
    db.add(DataReconciliation(release_id=rel.id, official_release_id=official.id, manual_value=rel.actual,
                              official_value=official_value, official_source=source_name or source_key,
                              prior_status=prior))
    db.add(VerificationAttempt(release_id=rel.id, source_key=source_key, outcome="mismatch",
                               official_value=official_value))
    sev = "HIGH" if prior == VerificationStatus.USER_CONFIRMED.value else "MEDIUM"
    alert(db, "data_conflict", f"{ind.name} {rel.reference_period}: official value differs",
          f"Your {'confirmed ' if sev == 'HIGH' else ''}value {rel.actual} differs from "
          f"{source_name or source_key} {official_value}. Both values are kept. Choose which to use.",
          sev, entity="economic_release", entity_id=rel.id, currency=ind.currency,
          central_bank_code=ind.central_bank_code, manual_value=rel.actual, official_value=official_value)
    audit(db, "economic_release", rel.id, "conflict", None, source=source_key, official_value=official_value,
          prior_status=prior)
    return "mismatch"


def resolve_conflict(db: Session, reconciliation_id: int, resolution: str, user_id: int | None = None) -> dict:
    """resolution: 'use_official' or 'keep_manual'."""
    from app.services import recompute

    rec = db.get(DataReconciliation, reconciliation_id)
    if rec is None:
        raise LookupError("Reconciliation not found")
    if rec.resolved:
        raise ValueError("Already resolved")
    manual = db.get(EconomicRelease, rec.release_id)
    official = db.get(EconomicRelease, rec.official_release_id) if rec.official_release_id else None
    if resolution == "use_official":
        if official is None:
            raise ValueError("No official value stored")
        manual.is_current = False
        manual.verification_status = VerificationStatus.SUPERSEDED.value
        manual.superseded_by_id = official.id
        official.is_current = True
    elif resolution == "keep_manual":
        restored = rec.prior_status if rec.prior_status in (
            VerificationStatus.UNVERIFIED.value, VerificationStatus.USER_CONFIRMED.value) \
            else VerificationStatus.UNVERIFIED.value
        manual.verification_status = restored
        manual.is_current = True
        if official is not None:
            official.is_current = False
    else:
        raise ValueError("resolution must be 'use_official' or 'keep_manual'")
    rec.resolved, rec.resolution, rec.resolved_by, rec.resolved_at = True, resolution, user_id, utcnow()
    audit(db, "data_reconciliation", rec.id, "resolved", user_id, resolution=resolution,
          manual_value=rec.manual_value, official_value=rec.official_value)
    db.commit()
    job = recompute.trigger(db, "release", manual.id, **_ctx_for(db, manual))
    return {"reconciliation_id": rec.id, "resolution": resolution, "recompute": job.summary}


def pending_verification(db: Session) -> list[EconomicRelease]:
    return list(db.scalars(select(EconomicRelease).where(
        EconomicRelease.verification_status.in_([VerificationStatus.UNVERIFIED.value,
                                                 VerificationStatus.USER_CONFIRMED.value]),
        EconomicRelease.input_method != "automated")))


def verify_pending(db: Session, fetchers: dict[str, OfficialFetcher] | None = None) -> dict:
    """Retry official sources for every UNVERIFIED / USER_CONFIRMED value (Section 66.12)."""
    from app.services import recompute

    if fetchers is None:
        from app.ingestion.registry import official_fetchers

        fetchers = official_fetchers()
    stats = defaultdict(int)
    changed_ctx = defaultdict(set)
    cutoff = utcnow() - timedelta(minutes=settings.verification_retry_minutes)
    for rel in pending_verification(db):
        last = db.scalar(select(func.max(VerificationAttempt.attempted_at))
                         .where(VerificationAttempt.release_id == rel.id))
        if last is not None:
            if last.tzinfo is None:
                from datetime import timezone

                last = last.replace(tzinfo=timezone.utc)
            if last > cutoff:
                stats["skipped_recent"] += 1
                continue
        ind = db.get(Indicator, rel.indicator_id)
        fetch = None
        key = None
        for k in ([ind.official_source_key] if ind.official_source_key else []) + ["fred"]:
            if k in fetchers:
                fetch, key = fetchers[k], k
                break
        if fetch is None:
            stats["no_connector"] += 1
            continue
        try:
            val = fetch(ind, rel.reference_period)
        except Exception as exc:
            db.add(VerificationAttempt(release_id=rel.id, source_key=key, outcome="unreachable",
                                       error=str(exc)[:500]))
            stats["unreachable"] += 1
            continue
        if val is None:
            db.add(VerificationAttempt(release_id=rel.id, source_key=key, outcome="no_data"))
            stats["no_data"] += 1
            continue
        outcome = reconcile(db, rel, val, key)
        stats[outcome] += 1
        for k2, v in _ctx_for(db, rel).items():
            changed_ctx[k2] |= v
    db.commit()
    if changed_ctx:
        recompute.trigger(db, "release", None, **changed_ctx)
    return dict(stats)


# ---------------------------------------------------------------------------
# data health (Section 66.13)
# ---------------------------------------------------------------------------

def data_health(db: Session) -> dict:
    now = utcnow()
    sources = []
    for src, h in db.execute(select(Source, SourceHealth).join(SourceHealth, SourceHealth.source_id == Source.id)
                             .order_by(Source.tier, Source.key)):
        status = h.status
        if h.last_success_at is not None and src.freshness_minutes:
            ls = h.last_success_at if h.last_success_at.tzinfo else h.last_success_at.replace(
                tzinfo=now.tzinfo)
            age = (now - ls).total_seconds() / 60
            if status == SourceStatus.OK.value and age > 2 * src.freshness_minutes:
                status = SourceStatus.STALE.value
            elif status == SourceStatus.OK.value and age > src.freshness_minutes:
                status = SourceStatus.DELAYED.value
        sources.append({
            "key": src.key, "name": src.name, "tier": src.tier, "kind": src.kind, "enabled": src.enabled,
            "status": status if src.kind != "manual" else "OK", "last_success_at": h.last_success_at,
            "last_attempt_at": h.last_attempt_at, "expected_next_at": h.expected_next_at, "retries": h.retries,
            "last_error": h.last_error, "needs_manual_input": status in ("FAILED", "STALE"),
        })
    counts = {s: db.scalar(select(func.count(EconomicRelease.id)).where(
        EconomicRelease.verification_status == s, EconomicRelease.is_current.is_(True))) or 0
        for s in (VerificationStatus.UNVERIFIED.value, VerificationStatus.USER_CONFIRMED.value)}
    counts[VerificationStatus.CONFLICT.value] = db.scalar(select(func.count(DataReconciliation.id)).where(
        DataReconciliation.resolved.is_(False))) or 0
    manual_total = db.scalar(select(func.count(EconomicRelease.id)).where(
        EconomicRelease.input_method != "automated", EconomicRelease.is_current.is_(True))) or 0
    failing = [s for s in sources if s["status"] in ("FAILED", "STALE")]
    overall = "OK"
    if counts[VerificationStatus.CONFLICT.value] or failing:
        overall = "ATTENTION"
    if len(failing) >= 3:
        overall = "DEGRADED"
    missing = missing_scheduled(db)
    return {"overall": overall, "sources": sources, "manual_records": manual_total,
            "unverified": counts[VerificationStatus.UNVERIFIED.value],
            "user_confirmed_awaiting": counts[VerificationStatus.USER_CONFIRMED.value],
            "conflicts": counts[VerificationStatus.CONFLICT.value], "missing_scheduled": missing}


def missing_scheduled(db: Session) -> list[dict]:
    """Events whose release time has passed with no actual recorded (66.1)."""
    from app.models import EconomicEvent

    now = utcnow()
    out = []
    q = (select(EconomicEvent, Indicator).join(Indicator, EconomicEvent.indicator_id == Indicator.id)
         .where(EconomicEvent.scheduled_at.is_not(None), EconomicEvent.scheduled_at <= now,
                EconomicEvent.scheduled_at >= now - timedelta(days=14)))
    for ev, ind in db.execute(q):
        has = db.scalar(select(func.count(EconomicRelease.id)).where(EconomicRelease.event_id == ev.id))
        if not has:
            out.append({"event_id": ev.id, "indicator_code": ind.code, "indicator": ind.name,
                        "reference_period": ev.reference_period, "scheduled_at": ev.scheduled_at,
                        "official_source": ind.official_source_key,
                        "message": f"{ind.name} was due at {ev.scheduled_at:%Y-%m-%d %H:%M} UTC. "
                                   "No actual value received from automated sources."})
    return out
