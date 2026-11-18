"""Type in any economic number straight from the Macro page heatmap, for data the feeds can't fetch.

Every edit goes through the calendar's quick-edit path (validation, revisions, audit, re-analysis).
If no calendar event exists yet for that indicator and period, one is created first, so the number
also shows on the economic calendar.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import EconomicEvent, Indicator
from app.services import data_access as da
from app.services import manual_service as ms

FIELDS = {"actual": "actual", "forecast": "consensus", "previous": "previous"}


def published_period(db: Session, ind: Indicator, at, below: str | None = None) -> str:
    """The newest period already released at `at`: from the calendar (UK PPI typed on 2 November is
    September's, since October's comes out on the 18th), else the release-date rule (the period before).
    Never the month or quarter still running."""
    from sqlalchemy import func, select

    from app.ingestion.forexfactory import reference_period

    rule = reference_period(ind.frequency or "monthly", at, "")
    cap = min(rule, below) if below else rule
    if ind.frequency in ("monthly", "quarterly"):
        p = db.scalar(select(func.max(EconomicEvent.reference_period)).where(
            EconomicEvent.indicator_id == ind.id, EconomicEvent.scheduled_at <= at,
            EconomicEvent.reference_period <= cap))
        if p:
            return p
    return cap


def default_period(ind: Indicator, db: Session | None = None) -> str:
    """The period a number typed in today most likely describes (see published_period)."""
    if db is not None:
        return published_period(db, ind, utcnow())
    from app.ingestion.forexfactory import reference_period

    return reference_period(ind.frequency or "monthly", utcnow(), "")


def _prev(period: str) -> str:
    if "Q" in period:
        y, q = int(period[:4]), int(period[-1])
        return f"{y}Q{q - 1}" if q > 1 else f"{y - 1}Q4"
    y, m = int(period[:4]), int(period[5:7])
    return f"{y}-{m - 1:02d}" if m > 1 else f"{y - 1}-12"


def fix_too_new_periods(db: Session) -> int:
    """Numbers typed in on the Macro page before this fix were filed under the month (or quarter) they were
    typed in: October's UK PPI typed on 2 November became "2026-11", which then sat above the calendar's
    real figures. Move each to the period before; where the calendar already has that period, the typed copy
    is retired (kept for the audit trail)."""
    from sqlalchemy import select

    from app.models import EconomicRelease

    rows = db.scalars(select(EconomicRelease).where(EconomicRelease.is_current.is_(True),
                                                    EconomicRelease.input_method != "automated")).all()
    fixed = 0
    for rel in rows:
        ind = db.get(Indicator, rel.indicator_id)
        made = rel.created_at
        if ind is None or made is None or ind.frequency not in ("monthly", "quarterly"):
            continue
        p = rel.reference_period or ""
        if ind.frequency == "monthly":
            too_new = p == f"{made.year}-{made.month:02d}" and made.day < 20
        else:
            too_new = p == f"{made.year}Q{(made.month - 1) // 3 + 1}"
        if not too_new:
            continue
        target = published_period(db, ind, made, below=_prev(p))
        old_ev = db.get(EconomicEvent, rel.event_id) if rel.event_id else None
        there = da.current_release(db, ind.id, target)
        if there is not None:
            rel.is_current, rel.verification_status, rel.superseded_by_id = False, "SUPERSEDED", there.id
            if there.event_id:
                rel.event_id = there.event_id  # so the mislabelled event can go
            rel.reference_period = target
        else:
            ev = da.event_for(db, ind.id, target)
            if ev is None and old_ev is not None and old_ev.reference_period == p:
                old_ev.reference_period = target  # the event itself was mislabelled
                ev = old_ev
            elif ev is None:
                ev = EconomicEvent(indicator_id=ind.id, reference_period=target, importance=ind.importance,
                                   scheduled_at=made, event_type="release")
                db.add(ev)
                db.flush()
            rel.reference_period, rel.event_id = target, ev.id
        db.flush()
        if old_ev is not None and old_ev.reference_period == p:
            from app.ingestion.markets import _event_unused

            if old_ev.consensus_source in (None, "manual") and _event_unused(db, old_ev.id):
                db.delete(old_ev)
        fixed += 1
    if fixed:
        db.commit()
    return fixed


def check_period(ind: Indicator, period: str | None, db: Session | None = None) -> str:
    per = (period or default_period(ind, db)).strip().upper()
    if ind.frequency == "quarterly":
        if not re.fullmatch(r"\d{4}Q[1-4]", per):
            raise ValueError("Period should look like 2026Q3")
    elif ind.frequency == "weekly":
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])-\d{2}", per):
            raise ValueError("Period should be the week-ending date, like 2026-10-17")
    elif not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", per):
        raise ValueError("Period should look like 2026-09")
    return per


def _number(value, field: str) -> float | None:
    if value is None or str(value).strip() == "":
        if field == "actual":
            raise ValueError("Type a number, e.g. 51.3")
        return None  # an empty forecast or previous clears it
    try:
        v = float(str(value).replace(",", "").replace("%", "").strip())
    except ValueError:
        raise ValueError("Type a number, e.g. 51.3")
    if not -1_000_000 <= v <= 1_000_000:
        raise ValueError("That number is out of range")
    return v


def edit(db: Session, code: str, field: str, value, period: str | None, reason: str | None,
         user_id: int | None) -> dict:
    if field not in FIELDS:
        raise ValueError("Field must be actual, forecast or previous")
    ind = da.indicator_by_code(db, code.upper())
    if ind is None:
        raise LookupError(f"Unknown indicator {code}")
    v = _number(value, field)
    per = check_period(ind, period, db)
    ev = da.event_for(db, ind.id, per)
    if ev is None:
        ev = EconomicEvent(indicator_id=ind.id, reference_period=per, scheduled_at=utcnow(),
                           importance=ind.importance, event_type="release")
        if field == "actual":  # keep the jump checks working: previous = the reading before
            earlier = [r for r in da.current_series(db, ind.id, 36) if r.reference_period < per]
            ev.previous = earlier[-1].actual if earlier else None
        db.add(ev)
        db.commit()
    res = ms.quick_edit_event(db, ev.id, FIELDS[field], v, user_id, reason)
    from app.services import setups as sv
    from app.services import setups_table

    setups_table.clear_cache()
    sv.clear_cache()
    return {"indicator": ind.code, "field": field, "period": per, **res}
