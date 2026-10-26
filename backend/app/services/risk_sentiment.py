"""Collect daily market series for the risk sentiment score, compute it and store it.

Daily history comes from FRED (free): VIX, the US high-yield spread, the S&P 500, the 10-year yield and
daily FX rates (these FX rates are published weekly, so they can be a few days behind). Gold comes from
one daily Twelve Data request when a key is set. Values are kept in indicator_observations under
"RISK:<name>" so the score can be rebuilt at any time.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import risk as rk
from app.config import settings
from app.ingestion.base import SourceUnavailable
from app.models import IndicatorObservation, RiskSentiment, Source
from app.services.audit import alert

log = logging.getLogger(__name__)

# our name -> (FRED series, how to turn it into our quote)
FRED_SERIES = {
    "vix": ("VIXCLS", None), "hy_oas": ("BAMLH0A0HYM2", None), "spx": ("SP500", None), "us10y": ("DGS10", None),
    "usdjpy": ("DEXJPUS", None), "usdchf": ("DEXSZUS", None), "audusd": ("DEXUSAL", None),
    "usdzar": ("DEXSFUS", None), "usdmxn": ("DEXMXUS", None),
}
PREFIX = "RISK:"


def _store(db: Session, name: str, obs: list[tuple[date, float]]) -> int:
    key = PREFIX + name
    have = {d for (d,) in db.execute(select(IndicatorObservation.obs_date).where(IndicatorObservation.series == key))}
    n = 0
    for d, v in obs:
        if d not in have:
            db.add(IndicatorObservation(series=key, obs_date=d, value=v))
            n += 1
    return n


def _gold_daily() -> list[tuple[date, float]]:
    import requests

    r = requests.get("https://api.twelvedata.com/time_series",
                     params={"symbol": "XAU/USD", "interval": "1day", "outputsize": 120,
                             "apikey": settings.twelvedata_api_key, "timezone": "UTC"}, timeout=30)
    data = r.json()
    if r.status_code >= 400 or data.get("status") == "error":
        raise SourceUnavailable(f"Twelve Data gold: {data.get('message', r.status_code)}")
    return [(date.fromisoformat(v["datetime"][:10]), float(v["close"])) for v in data.get("values", [])]


def collect(db: Session) -> tuple[int, list[str]]:
    from app.ingestion.fred import fetch_observations

    start = (date.today() - timedelta(days=450)).isoformat()
    n, failed = 0, []
    for name, (series, _) in FRED_SERIES.items():
        try:
            n += _store(db, name, fetch_observations(series, start))
        except Exception as exc:  # one series failing must not stop the rest
            failed.append(f"{series}: {exc}")
    if settings.twelvedata_api_key:
        try:
            n += _store(db, "gold", _gold_daily())
        except Exception as exc:
            failed.append(f"gold: {exc}")
    db.commit()
    return n, failed


def load_series(db: Session) -> tuple[dict[str, list[float]], str | None]:
    out: dict[str, list[float]] = {}
    latest = None
    for name in list(FRED_SERIES) + ["gold"]:
        rows = list(db.execute(select(IndicatorObservation.obs_date, IndicatorObservation.value)
                               .where(IndicatorObservation.series == PREFIX + name)
                               .order_by(IndicatorObservation.obs_date)))
        out[name] = [v for _, v in rows]
        if rows and name in ("vix", "spx", "hy_oas"):
            d = rows[-1][0].isoformat()
            latest = max(latest, d) if latest else d
    return out, latest


def compute(db: Session) -> RiskSentiment:
    series, latest = load_series(db)
    res = rk.evaluate(series)
    prev = latest_reading(db)
    row = RiskSentiment(score=res.score, label=res.label, data_date=latest, coverage=res.coverage,
                        divergence=res.divergence, notes=res.notes, missing=res.missing,
                        components=[c.__dict__ for c in res.components])
    db.add(row)
    if prev is not None and prev.label != res.label and res.label != "No data" and prev.label != "No data":
        direct = {prev.label, res.label} == {"Risk-On", "Risk-Off"}
        alert(db, "risk_sentiment", f"Risk sentiment turned {res.label} ({res.score:.0f}/100)",
              f"Previously {prev.label} ({prev.score:.0f}/100). {rk.FX_IMPLICATION[res.label]}",
              "HIGH" if direct else "MEDIUM", entity="risk_sentiment")
    db.commit()
    return row


def latest_reading(db: Session) -> RiskSentiment | None:
    return db.scalar(select(RiskSentiment).order_by(RiskSentiment.as_of.desc(), RiskSentiment.id.desc()))


def run_risk(db: Session, src: Source) -> int:
    from app.services import recompute

    n, failed = collect(db)
    row = compute(db)
    if failed:
        log.info("Risk sentiment: some series failed: %s", "; ".join(failed))
    if row.score is None:
        raise SourceUnavailable("No market series came back from FRED. Check FRED_API_KEY. "
                                + ("First error: " + failed[0] if failed else ""))
    recompute.trigger(db, "market_data", None)  # the macro regime and currency scores use the risk mood
    return n


def load_dated(db: Session) -> dict[str, list[tuple]]:
    out = {}
    for name in list(FRED_SERIES) + ["gold"]:
        out[name] = list(db.execute(select(IndicatorObservation.obs_date, IndicatorObservation.value)
                                    .where(IndicatorObservation.series == PREFIX + name)
                                    .order_by(IndicatorObservation.obs_date)))
    return out


def reading(db: Session, horizon: str = "daily", history_days: int = 120) -> dict:
    """The score for one time frame, worked out from the stored daily series, plus its history
    (one point per market day, each using only the data known on that day)."""
    dated = load_dated(db)
    series = {k: [v for _, v in rows] for k, rows in dated.items()}
    res = rk.evaluate(series, horizon)
    anchor = [d for d, _ in dated.get("vix") or dated.get("spx") or []]
    latest = anchor[-1].isoformat() if anchor else None
    history = []
    for d in anchor[-history_days:]:
        cut = {k: [v for dd, v in rows if dd <= d] for k, rows in dated.items()}
        r = rk.evaluate(cut, horizon)
        if r.score is not None:
            history.append({"date": d.isoformat(), "score": r.score, "label": r.label})
    return {"horizon": horizon, "score": res.score, "label": res.label, "data_date": latest,
            "coverage": res.coverage, "divergence": res.divergence, "notes": res.notes, "missing": res.missing,
            "components": [c.__dict__ for c in res.components], "history": history}
