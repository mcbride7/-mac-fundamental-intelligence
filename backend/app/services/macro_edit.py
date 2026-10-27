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


def default_period(ind: Indicator) -> str:
    now = utcnow()
    if ind.frequency == "quarterly":
        return f"{now.year}Q{(now.month - 1) // 3 + 1}"
    if ind.frequency == "weekly":
        return now.date().isoformat()
    return now.strftime("%Y-%m")


def check_period(ind: Indicator, period: str | None) -> str:
    per = (period or default_period(ind)).strip().upper()
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
    per = check_period(ind, period)
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
