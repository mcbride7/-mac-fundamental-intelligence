"""Extra daily series for Intermarket (stored as IM:<name>):
  FRED   DFII10 (US 10-year real yield, TIPS), WALCL (Fed balance sheet), WTREGEN (Treasury General Account),
         RRPONTSYD (overnight reverse repo)  ->  US net liquidity = balance sheet - TGA - reverse repo
  Twelve Data (US-listed funds, free plan)  CPER (copper), EWG (Germany / DAX)
"""
from __future__ import annotations

import logging
import time as _time
from datetime import date, timedelta

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.base import SourceUnavailable
from app.models import IndicatorObservation, Source

log = logging.getLogger(__name__)
PREFIX = "IM:"
FRED = {"REAL10Y": "DFII10", "WALCL": "WALCL", "TGA": "WTREGEN", "RRP": "RRPONTSYD"}
TWELVE = {"COPPER": "CPER", "DAX": "EWG"}


def _store(db: Session, name: str, obs: list[tuple[date, float]]) -> int:
    key = PREFIX + name
    have = {d for (d,) in db.execute(select(IndicatorObservation.obs_date).where(IndicatorObservation.series == key))}
    new = [{"series": key, "obs_date": d, "value": v} for d, v in obs if d not in have]
    for i in range(0, len(new), 2000):
        db.execute(insert(IndicatorObservation), new[i:i + 2000])
    db.commit()
    return len(new)


def run_intermarket(db: Session, src: Source) -> int:
    from app.ingestion.fred import fetch_observations
    from app.services.seasonality import _twelvedata_daily

    n, failed = 0, []
    start = (date.today() - timedelta(days=365 * 6)).isoformat()
    for name, series in FRED.items():
        try:
            n += _store(db, name, fetch_observations(series, start))
        except Exception as exc:
            db.rollback()
            failed.append(f"{name}: {exc}"[:150])
    for i, (name, sym) in enumerate(TWELVE.items()):
        if not settings.twelvedata_api_key:
            failed.append(f"{name}: no TWELVEDATA_API_KEY")
            continue
        try:
            if i:
                _time.sleep(8)  # free plan: about 8 requests a minute
            n += _store(db, name, _twelvedata_daily(sym))
        except Exception as exc:
            db.rollback()
            failed.append(f"{name}: {exc}"[:150])
    from app.services import intermarket

    intermarket.clear_cache()
    if len(failed) == len(FRED) + len(TWELVE):
        raise SourceUnavailable("; ".join(failed))
    return (n, "Some series failed: " + "; ".join(failed)) if failed else n
