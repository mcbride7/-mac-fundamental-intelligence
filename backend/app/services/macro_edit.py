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
        # a period the calendar shows coming out after `at` wasn't out yet, nor anything after it
        # (US JOLTS typed on 2 Nov is August's or earlier: September's came out on 3 Nov)
        nxt = db.scalar(select(func.min(EconomicEvent.reference_period)).where(
            EconomicEvent.indicator_id == ind.id, EconomicEvent.scheduled_at > at,
            EconomicEvent.reference_period <= cap))
        if nxt:
            cap = _prev(nxt)
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


def _start(period: str):
    from datetime import datetime, timezone

    y = int(period[:4])
    m = (int(period[-1]) - 1) * 3 + 1 if "Q" in period else int(period[5:7])
    return datetime(y, m, 1, tzinfo=timezone.utc)


def _aware(t):
    from datetime import timezone

    return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)


def _target_period(db: Session, ind: Indicator, rel, made) -> str | None:
    """The period a typed-in number really belongs to, or None when its period is fine."""
    from datetime import timedelta

    from sqlalchemy import select

    from app.models import EconomicRelease

    p = rel.reference_period or ""
    own = db.get(EconomicEvent, rel.event_id) if rel.event_id else None
    at = _aware((own.scheduled_at if own is not None and own.scheduled_at else None) or rel.released_at)
    # 1. the same release: the calendar filled an event at the same time under another period
    if at is not None:
        for ev in db.scalars(select(EconomicEvent).where(
                EconomicEvent.indicator_id == ind.id, EconomicEvent.reference_period != p,
                EconomicEvent.scheduled_at >= at - timedelta(hours=18),
                EconomicEvent.scheduled_at <= at + timedelta(hours=18))).all():
            if db.scalar(select(EconomicRelease.id).where(
                    EconomicRelease.event_id == ev.id, EconomicRelease.is_current.is_(True),
                    EconomicRelease.input_method == "automated")):
                return ev.reference_period
    # 2. a period that hadn't started, or was still running, when the number was typed
    start = _start(p)
    if start > made:
        return published_period(db, ind, made)
    if ind.frequency == "monthly" and (start.year, start.month) == (made.year, made.month) and made.day < 20:
        return published_period(db, ind, made, below=_prev(p))
    if ind.frequency == "quarterly" and p == f"{made.year}Q{(made.month - 1) // 3 + 1}":
        return published_period(db, ind, made, below=_prev(p))
    # 3. the calendar shows this period (or an earlier one) still to come after the number was typed
    later = db.scalar(select(EconomicEvent.reference_period).where(
        EconomicEvent.indicator_id == ind.id, EconomicEvent.reference_period <= p,
        EconomicEvent.scheduled_at > made + timedelta(hours=18),
        EconomicEvent.id != (own.id if own is not None else -1)).order_by(EconomicEvent.reference_period))
    if later:
        return published_period(db, ind, made, below=_prev(later))
    return None


def fix_too_new_periods(db: Session) -> int:
    """Numbers typed in on the Macro page or the calendar that were filed under the wrong period: the month
    or quarter they were typed in (October's UK PPI typed on 2 November became "2026-11"), a period that
    hadn't even started (ISM services "2026-12", Japan GDP "2027Q1"), or the period after the release they
    belong to (Euro Area PPI typed on 29 October as October; September's came out on 5 November). Each is
    moved to its real period; where the calendar already has that period, the typed copy is retired (kept for
    the audit trail). Numbers you confirmed are moved too: the period, not the number, was wrong."""
    from sqlalchemy import select

    from app.models import EconomicRelease

    rows = db.scalars(select(EconomicRelease).where(EconomicRelease.is_current.is_(True),
                                                    EconomicRelease.input_method != "automated")).all()
    fixed = 0
    for rel in rows:
        ind = db.get(Indicator, rel.indicator_id)
        made = _aware(rel.created_at)
        if ind is None or made is None or ind.frequency not in ("monthly", "quarterly"):
            continue
        p = rel.reference_period or ""
        try:
            target = _target_period(db, ind, rel, made)
        except (ValueError, IndexError):
            continue
        if not target or target == p:
            continue
        old_ev = db.get(EconomicEvent, rel.event_id) if rel.event_id else None
        there = da.current_release(db, ind.id, target)
        if there is not None and there.id != rel.id:
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

            if old_ev.consensus_source in (None, "manual", "fmp") and _event_unused(db, old_ev.id):
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
