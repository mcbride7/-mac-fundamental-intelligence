"""Economic calendar and data APIs (Sections 14-15, 29, 48, 57)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Auth, current_user_id, get_db, row
from app.core.verification import badge
from app.db import utcnow
from app.engines.release_engine import event_report
from app.models import EconomicEvent, EconomicSurprise, ForecastError, Indicator
from app.models.overrides import EventOverride
from app.services import data_access as da
from app.services import manual_service as ms

router = APIRouter(prefix="/api", tags=["economic data"], dependencies=[Auth])


class EventIn(BaseModel):
    indicator_code: str
    reference_period: str
    scheduled_at: datetime | None = None
    consensus: float | None = None
    previous: float | None = None
    consensus_source: str | None = None


@router.get("/economic-calendar")
def calendar(start: date | None = None, end: date | None = None, country: str | None = None,
             currency: str | None = None, indicator: str | None = None, importance: str | None = None,
             central_bank: str | None = None, category: str | None = None, status: str | None = None,
             asset: str | None = None, db: Session = Depends(get_db)):
    start_dt = datetime.combine(start or (date.today() - timedelta(days=7)), time(0), tzinfo=timezone.utc)
    end_dt = datetime.combine(end or (date.today() + timedelta(days=14)), time(23, 59), tzinfo=timezone.utc)
    q = (select(EconomicEvent, Indicator).join(Indicator, EconomicEvent.indicator_id == Indicator.id)
         .where(EconomicEvent.scheduled_at >= start_dt, EconomicEvent.scheduled_at <= end_dt))
    if country:
        q = q.where(Indicator.country == country.upper())
    if currency:
        q = q.where(Indicator.currency == currency.upper())
    if asset and len(asset) == 6:
        q = q.where(Indicator.currency.in_([asset[:3].upper(), asset[3:].upper()]))
    if indicator:
        q = q.where(Indicator.code == indicator.upper())
    if importance:
        q = q.where(Indicator.importance == importance.lower())
    if central_bank:
        q = q.where(Indicator.central_bank_code == central_bank.upper())
    if category:
        q = q.where(Indicator.category == category.lower())
    out = []
    now = utcnow()
    for ev, ind in db.execute(q.order_by(EconomicEvent.scheduled_at)):
        rel = da.current_release(db, ind.id, ev.reference_period)
        s = db.scalar(select(EconomicSurprise).where(EconomicSurprise.release_id == rel.id)) if rel else None
        fe = db.scalar(select(ForecastError).where(ForecastError.release_id == rel.id,
                                                   ForecastError.basis == "real_time")) if rel else None
        proj = fe.cb_projection if fe else None
        if proj is None and ind.projection_variable and ind.central_bank_code:
            cb = da.cb_by_code(db, ind.central_bank_code)
            pr = da.projection_for(db, cb.id, ind.projection_variable, ev.reference_period[:4]) if cb else None
            proj = pr[0].value if pr else None
        ov = db.scalar(select(EventOverride).where(EventOverride.event_id == ev.id, EventOverride.field == "surprise"))
        cons = (rel.consensus if rel and rel.consensus is not None else ev.consensus)
        calc = round(rel.actual - cons, 4) if rel and cons is not None else None
        sched = ev.scheduled_at if ev.scheduled_at.tzinfo else ev.scheduled_at.replace(tzinfo=timezone.utc)
        data_status = rel.verification_status if rel else ("MISSING" if sched <= now else "SCHEDULED")
        if status and data_status.lower() != status.lower():
            continue
        out.append({
            "event_id": ev.id, "date": sched.date().isoformat(), "time": sched.strftime("%H:%M"),
            "scheduled_at": sched, "country": ind.country, "currency": ind.currency, "indicator": ind.code,
            "event": ind.name, "reference_period": ev.reference_period, "importance": ind.importance,
            "previous": ev.previous, "market_forecast": ev.consensus, "central_bank_projection": proj,
            "actual": rel.actual if rel else None, "unit": ind.unit, "release_id": rel.id if rel else None,
            "surprise": s.market_surprise if s else None, "surprise_class": s.classification if s else None,
            "surprise_edited": ov is not None, "surprise_calculated": calc,
            "surprise_reason": ov.reason if ov else None,
            "projection_editable": bool(ind.projection_variable and ind.central_bank_code),
            "data_status": data_status,
            "badge": badge(rel.verification_status, rel.confirmation_basis) if rel else None,
            "needs_manual_input": data_status == "MISSING",
        })
    return out


@router.post("/economic-events")
def add_event(body: EventIn, db: Session = Depends(get_db)):
    ind = da.indicator_by_code(db, body.indicator_code.upper())
    if ind is None:
        raise HTTPException(404, "Unknown indicator")
    ev = da.event_for(db, ind.id, body.reference_period) or EconomicEvent(indicator_id=ind.id,
                                                                           reference_period=body.reference_period,
                                                                           importance=ind.importance)
    db.add(ev)
    for k in ("scheduled_at", "consensus", "previous", "consensus_source"):
        v = getattr(body, k)
        if v is not None:
            setattr(ev, k, v)
    db.commit()
    return row(ev)


class QuickEditIn(BaseModel):
    field: str  # actual | consensus | previous | cb_projection | surprise
    value: float | None = None
    reason: str | None = None  # needed when the value looks unusual (e.g. a possible decimal slip)


@router.patch("/economic-events/{event_id}")
def quick_edit(event_id: int, body: QuickEditIn, db: Session = Depends(get_db),
               user_id: int = Depends(current_user_id)):
    try:
        return ms.quick_edit_event(db, event_id, body.field, body.value, user_id, body.reason)
    except ms.CommitBlocked as exc:
        raise HTTPException(422, {"message": "Check this value", "problems": exc.problems})
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/economic-events/{event_id}")
def event_detail(event_id: int, db: Session = Depends(get_db)):
    ev = db.get(EconomicEvent, event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    rel = da.current_release(db, ev.indicator_id, ev.reference_period)
    ind = db.get(Indicator, ev.indicator_id)
    if rel is None:
        return {"event": {**row(ev), "indicator": ind.code, "name": ind.name}, "actual": None,
                "message": "No actual recorded yet. Provide it manually (screenshot, PDF, typed or URL)."}
    return event_report(db, rel.id)


@router.get("/economic-releases/{release_id}/report")
def release_report(release_id: int, db: Session = Depends(get_db)):
    try:
        return event_report(db, release_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.get("/economic-data")
def indicators(country: str | None = None, category: str | None = None, db: Session = Depends(get_db)):
    q = select(Indicator)
    if country:
        q = q.where(Indicator.country == country.upper())
    if category:
        q = q.where(Indicator.category == category.lower())
    out = []
    for ind in db.scalars(q.order_by(Indicator.country, Indicator.category, Indicator.code)):
        rel = da.latest_current(db, ind.id)
        out.append({"code": ind.code, "name": ind.name, "country": ind.country, "currency": ind.currency,
                    "category": ind.category, "unit": ind.unit, "importance": ind.importance,
                    "latest": rel.actual if rel else None, "period": rel.reference_period if rel else None,
                    "data_status": rel.verification_status if rel else None,
                    "badge": badge(rel.verification_status, rel.confirmation_basis) if rel else None})
    return out


@router.get("/economic-data/{indicator}")
def series(indicator: str, basis: str = "latest", limit: int = 60, db: Session = Depends(get_db)):
    """basis=latest (latest revised values) or real_time (first prints)."""
    ind = da.indicator_by_code(db, indicator.upper())
    if ind is None:
        raise HTTPException(404, "Unknown indicator")
    cur = da.current_series(db, ind.id, limit)
    out = []
    for r in cur:
        all_rows = da.releases_for_period(db, ind.id, r.reference_period)
        first = da.first_release(db, ind.id, r.reference_period) or r
        val = first.actual if basis == "real_time" else r.actual
        out.append({"period": r.reference_period, "value": val, "release_id": r.id,
                    "status": r.verification_status, "badge": badge(r.verification_status, r.confirmation_basis),
                    "input_method": r.input_method,
                    "revisions": [{"revision": x.revision_number, "value": x.actual, "status": x.verification_status,
                                   "released_at": x.released_at, "current": x.is_current} for x in all_rows]})
    return {"indicator": {"code": ind.code, "name": ind.name, "unit": ind.unit, "country": ind.country,
                          "category": ind.category, "transform": ind.transform}, "basis": basis, "series": out}


@router.get("/indicators/catalogue")
def catalogue(db: Session = Depends(get_db)):
    return [{"code": i.code, "name": i.name, "country": i.country, "unit": i.unit, "frequency": i.frequency,
             "central_bank": i.central_bank_code} for i in db.scalars(select(Indicator).order_by(Indicator.code))]

