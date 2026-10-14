"""FRED connector: US economic releases and Treasury yields, plus the official
value lookup used to verify manual data."""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.enums import VerificationStatus
from app.db import utcnow
from app.ingestion.base import SourceUnavailable, http_get
from app.models import BondYield, EconomicEvent, EconomicRelease, Indicator, IndicatorObservation, Source
from app.services import data_access as da
from app.services.verification_service import reconcile

BASE = "https://api.stlouisfed.org/fred/series/observations"
YIELD_SERIES = {"2Y": "DGS2", "5Y": "DGS5", "10Y": "DGS10", "30Y": "DGS30"}


def fetch_observations(series: str, start: str = "2015-01-01") -> list[tuple[date, float]]:
    if not settings.fred_api_key:
        raise SourceUnavailable("FRED_API_KEY not set")
    r = http_get(BASE, {"series_id": series, "api_key": settings.fred_api_key, "file_type": "json",
                        "observation_start": start})
    out = []
    for o in r.json().get("observations", []):
        if o.get("value") in (".", "", None):
            continue
        out.append((date.fromisoformat(o["date"]), float(o["value"])))
    return out


def to_period(d: date, frequency: str) -> str:
    if frequency == "quarterly":
        return f"{d.year}Q{(d.month - 1) // 3 + 1}"
    return f"{d.year}-{d.month:02d}"


def transform(obs: list[tuple[date, float]], how: str | None, frequency: str) -> list[tuple[str, float]]:
    """Convert raw levels into the indicator's published form."""
    vals = [v for _, v in obs]
    periods = [to_period(d, frequency) for d, _ in obs]
    out: list[tuple[str, float]] = []
    lag_y = 4 if frequency == "quarterly" else 12
    for i, (p, v) in enumerate(zip(periods, vals)):
        if how == "yoy":
            if i >= lag_y and vals[i - lag_y]:
                out.append((p, round((v / vals[i - lag_y] - 1) * 100, 2)))
        elif how == "mom" or how == "qoq":
            if i >= 1 and vals[i - 1]:
                out.append((p, round((v / vals[i - 1] - 1) * 100, 2)))
        elif how == "qoq_saar":
            if i >= 1 and vals[i - 1]:
                out.append((p, round(((v / vals[i - 1]) ** 4 - 1) * 100, 2)))
        elif how == "diff":
            if i >= 1:
                out.append((p, round(v - vals[i - 1], 1)))
        else:
            out.append((p, round(v, 3)))
    return out


def _monthly_last(obs: list[tuple[date, float]]) -> list[tuple[date, float]]:
    """Daily series (e.g. policy rate) -> last value per month."""
    last: dict[tuple[int, int], tuple[date, float]] = {}
    for d, v in obs:
        last[(d.year, d.month)] = (date(d.year, d.month, 1), v)
    return [last[k] for k in sorted(last)]


def ingest_indicator(db: Session, src: Source, ind: Indicator, start: str = "2015-01-01") -> int:
    obs = fetch_observations(ind.fred_series, start)
    if ind.frequency == "meeting":
        obs = _monthly_last(obs)
        freq = "monthly"
    else:
        freq = ind.frequency
    for d, v in obs[-400:]:
        if db.scalar(select(IndicatorObservation.id).where(IndicatorObservation.series == ind.fred_series,
                                                           IndicatorObservation.obs_date == d,
                                                           IndicatorObservation.vintage.is_(None))) is None:
            db.add(IndicatorObservation(series=ind.fred_series, obs_date=d, value=v))
    n = 0
    for period, value in transform(obs, ind.transform, freq):
        n += upsert_official_release(db, src, ind, period, value)
    return n


def upsert_official_release(db: Session, src: Source, ind: Indicator, period: str, value: float,
                            consensus: float | None = None, released_at: datetime | None = None) -> int:
    """Insert an official value. Existing official value that changed -> new revision.
    Existing manual value -> reconcile (match = VERIFIED, mismatch = CONFLICT)."""
    cur = da.current_release(db, ind.id, period)
    if cur is not None:
        if cur.input_method != "automated":
            if cur.verification_status in (VerificationStatus.UNVERIFIED.value,
                                           VerificationStatus.USER_CONFIRMED.value):
                reconcile(db, cur, value, src.key, src.name)
                return 1
            return 0
        if abs(cur.actual - value) < 1e-6:
            return 0
        # official revision: keep the old print, add a new revision row
        rev = EconomicRelease(event_id=cur.event_id, indicator_id=ind.id, reference_period=period, actual=value,
                              previous=cur.previous, consensus=cur.consensus, unit=ind.unit,
                              released_at=utcnow(), revision_number=cur.revision_number + 1, source_id=src.id,
                              source_name=src.name, input_method="automated",
                              verification_status=VerificationStatus.VERIFIED.value)
        db.add(rev)
        db.flush()
        cur.is_current = False
        cur.verification_status = VerificationStatus.SUPERSEDED.value
        cur.superseded_by_id = rev.id
        return 1
    ev = da.event_for(db, ind.id, period)
    prev_rel = da.latest_current(db, ind.id)
    if ev is None:
        ev = EconomicEvent(indicator_id=ind.id, reference_period=period, importance=ind.importance,
                           previous=prev_rel.actual if prev_rel else None, consensus=consensus,
                           scheduled_at=released_at)
        db.add(ev)
        db.flush()
    db.add(EconomicRelease(event_id=ev.id, indicator_id=ind.id, reference_period=period, actual=value,
                           previous=ev.previous, consensus=consensus if consensus is not None else ev.consensus,
                           unit=ind.unit, released_at=released_at or _period_end(period), revision_number=0,
                           source_id=src.id, source_name=src.name, input_method="automated",
                           verification_status=VerificationStatus.VERIFIED.value))
    return 1


def _period_end(period: str) -> datetime:
    if "Q" in period:
        y, q = int(period[:4]), int(period[-1])
        m = q * 3
    else:
        y, m = int(period[:4]), int(period[5:7])
    # data for a month is published in the following month
    m2, y2 = (m % 12) + 1, y + (1 if m == 12 else 0)
    return datetime.combine(date(y2, m2, 15), time(12, 30), tzinfo=timezone.utc)


def run_fred(db: Session, src: Source) -> int:
    n = 0
    for ind in db.scalars(select(Indicator).where(Indicator.fred_series.is_not(None))):
        n += ingest_indicator(db, src, ind)
    n += ingest_yields(db)
    db.commit()
    return n


def ingest_yields(db: Session, start: str = "2024-01-01") -> int:
    n = 0
    for tenor, series in YIELD_SERIES.items():
        for d, v in fetch_observations(series, start)[-300:]:
            ts = datetime.combine(d, time(21, 0), tzinfo=timezone.utc)
            if db.get(BondYield, ("US", tenor, ts)) is None:
                db.add(BondYield(country="US", tenor=tenor, ts=ts, yield_pct=v, source="FRED"))
                n += 1
    return n


def official_value(ind: Indicator, period: str) -> float | None:
    """Look up the official value for one period (used to verify manual data)."""
    if not ind.fred_series:
        return None
    y = int(period[:4])
    obs = fetch_observations(ind.fred_series, f"{y - 2}-01-01")
    freq = "monthly" if ind.frequency == "meeting" else ind.frequency
    if ind.frequency == "meeting":
        obs = _monthly_last(obs)
    for p, v in transform(obs, ind.transform, freq):
        if p == period:
            return v
    return None
