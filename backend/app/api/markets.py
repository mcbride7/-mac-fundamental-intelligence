"""Markets, currencies, bonds, yields, rates, divergence, regime, market reaction."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Auth, get_db, row, rows
from app.engines import currency_engine, market_engine
from app.engines import fundamentals as fnd
from app.models import (
    BondYield,
    CentralBank,
    MacroRegime,
    MarketPrice,
    MarketReaction,
    PolicyDivergence,
    RateExpectation,
)
from app.services import recompute

router = APIRouter(prefix="/api", tags=["markets"], dependencies=[Auth])


class PriceIn(BaseModel):
    symbol: str
    price: float
    ts: datetime | None = None
    asset_class: str = "fx"


class YieldIn(BaseModel):
    country: str
    tenor: str
    yield_pct: float
    ts: datetime | None = None


class RateExpIn(BaseModel):
    central_bank_code: str
    prob_cut: float
    prob_hold: float
    prob_hike: float
    meeting_date: str | None = None
    implied_change_bps: float | None = None
    implied_12m_change_bps: float | None = None
    source: str | None = None
    ts: datetime | None = None


@router.get("/markets")
def markets(db: Session = Depends(get_db)):
    return market_engine.markets_overview(db)


@router.post("/markets/prices")
def add_prices(body: list[PriceIn], db: Session = Depends(get_db)):
    from app.db import utcnow

    for p in body:
        db.merge(MarketPrice(symbol=p.symbol.upper().replace("/", ""), ts=p.ts or utcnow(), price=p.price,
                             asset_class=p.asset_class, source="api", input_method="typed",
                             verification_status="UNVERIFIED"))
    db.commit()
    job = recompute.trigger(db, "market_data", None)
    return {"stored": len(body), "recompute": job.summary}


@router.get("/currencies")
def currencies(db: Session = Depends(get_db)):
    scores = currency_engine.latest_scores(db)
    return {"scores": [{**row(s)} for s in sorted(scores.values(), key=lambda s: -s.total)],
            "heatmap": currency_engine.currency_heatmap(db)}


@router.get("/currencies/{ccy}")
def currency(ccy: str, db: Session = Depends(get_db)):
    ccy = ccy.upper()
    if ccy not in fnd.COUNTRY:
        raise HTTPException(404, "Unsupported currency")
    s = currency_engine.latest_scores(db).get(ccy)
    snap = fnd.build(db, ccy)
    return {"score": row(s), "snapshot": {k: v for k, v in snap.__dict__.items() if k not in ("cb", "points")},
            "evidence_quality": snap.evidence_quality}


@router.get("/bonds")
def bonds(db: Session = Depends(get_db)):
    return market_engine.yields_overview(db)


@router.get("/yields")
def yields(country: str = "US", tenor: str = "10Y", limit: int = 300, db: Session = Depends(get_db)):
    return rows(db.scalars(select(BondYield).where(BondYield.country == country.upper(), BondYield.tenor == tenor)
                           .order_by(BondYield.ts.desc()).limit(limit)))


@router.post("/yields")
def add_yields(body: list[YieldIn], db: Session = Depends(get_db)):
    from app.db import utcnow

    for y in body:
        db.merge(BondYield(country=y.country.upper(), tenor=y.tenor.upper(), ts=y.ts or utcnow(),
                           yield_pct=y.yield_pct, source="api", input_method="typed"))
    db.commit()
    job = recompute.trigger(db, "market_data", None)
    return {"stored": len(body), "recompute": job.summary}


@router.get("/rates")
def rates(db: Session = Depends(get_db)):
    return market_engine.rates_overview(db)


@router.post("/rates/expectations")
def add_rate_expectation(body: RateExpIn, db: Session = Depends(get_db)):
    from app.db import utcnow

    code = body.central_bank_code.upper()
    cb = db.scalar(select(CentralBank).where(CentralBank.code == code))
    if cb is None:
        raise HTTPException(404, "Unknown central bank")
    db.add(RateExpectation(central_bank_code=code, ts=body.ts or utcnow(), meeting_date=body.meeting_date,
                           prob_cut=body.prob_cut, prob_hold=body.prob_hold, prob_hike=body.prob_hike,
                           implied_change_bps=body.implied_change_bps,
                           implied_12m_change_bps=body.implied_12m_change_bps, source=body.source or "manual",
                           input_method="typed"))
    db.commit()
    job = recompute.trigger(db, "rate_expectation", None, central_banks={code}, currencies={cb.currency})
    return {"ok": True, "recompute": job.summary}


@router.get("/policy-divergence")
def divergence(db: Session = Depends(get_db)):
    out, seen = [], set()
    for d in db.scalars(select(PolicyDivergence).order_by(PolicyDivergence.as_of.desc())):
        key = (d.base_bank_id, d.quote_bank_id)
        if key in seen:
            continue
        seen.add(key)
        a, b = db.get(CentralBank, d.base_bank_id), db.get(CentralBank, d.quote_bank_id)
        out.append({"pair": f"{a.code}/{b.code}", "currencies": f"{a.currency}/{b.currency}",
                    "divergence": d.score_divergence, "implication": d.currency_implication, "details": d.details,
                    "as_of": d.as_of})
    return out


@router.get("/macro/regime")
def regime(db: Session = Depends(get_db)):
    cur = db.scalar(select(MacroRegime).order_by(MacroRegime.as_of.desc(), MacroRegime.id.desc()))
    # the regime is re-saved after every recalculation; list only the changes, each dated when it began
    recent = list(db.scalars(select(MacroRegime).order_by(MacroRegime.as_of.desc(), MacroRegime.id.desc()).limit(2000)))
    runs: list[list] = []
    for r in recent:
        if runs and (runs[-1][0].primary, runs[-1][0].secondary) == (r.primary, r.secondary):
            runs[-1].append(r)
        else:
            runs.append([r])
    hist = []
    for run in runs[:40]:
        start = run[-1]  # oldest entry of the run = when this regime began
        hist.append(row(start) | {"started_at": start.as_of, "ended_at": None, "readings": len(run)})
    for newer, older in zip(hist, hist[1:]):
        older["ended_at"] = newer["started_at"]
    return {"current": row(cur), "history": hist}


@router.get("/macro/risk")
def risk_sentiment(horizon: str = "daily", days: int = 120, db: Session = Depends(get_db)):
    """Risk-on / risk-off for one time frame (daily, weekly or monthly): score, signals, a plain-English note,
    the bullish / bearish lists with their % changes over that period, price boxes, and history."""
    from app.analytics.risk import FX_IMPLICATION, HORIZONS, RISK_OFF, RISK_ON, WEIGHTS, daily_evaluation, explain
    from app.services import heatmap as hm
    from app.services.daily_moves import LOOKBACK, daily_moves
    from app.services.risk_sentiment import reading

    if horizon not in HORIZONS:
        raise HTTPException(422, "horizon must be daily, weekly or monthly")
    r = reading(db, horizon, min(max(days, 10), 365))
    if r["score"] is None:
        return {"horizon": horizon, "current": None, "history": [], "tiles": _risk_tiles(db, LOOKBACK[horizon]),
                "thresholds": {"risk_on": RISK_ON, "risk_off": RISK_OFF}, "weights": WEIGHTS,
                "evaluation": daily_evaluation("No data") | {"moves": daily_moves(db, LOOKBACK[horizon])}}
    scores = {}
    if r["label"] == "Neutral":
        scores = {c: sum(1 if x["currency_impact"] == "Bullish" else -1 if x["currency_impact"] == "Bearish" else 0
                         for x in hm.rows_for(db, c)) for c in hm.CURRENCIES}
    history = r.pop("history")
    current = r | {"implication": FX_IMPLICATION.get(r["label"], ""),
                   "why": explain(r["label"], r["score"], r["components"])}
    return {"horizon": horizon, "current": current, "history": history,
            "thresholds": {"risk_on": RISK_ON, "risk_off": RISK_OFF}, "weights": WEIGHTS,
            "tiles": _risk_tiles(db, LOOKBACK[horizon]),
            "evaluation": daily_evaluation(r["label"], scores) | {"moves": daily_moves(db, LOOKBACK[horizon])}}


TILES = [("BTCUSD", "BTC/USD"), ("EURUSD", "EUR/USD"), ("SPX", "SPX500"), ("XAUUSD", "GOLD"), ("USDJPY", "USD/JPY")]


def _risk_tiles(db: Session, back: int = 1) -> list[dict]:
    """Price boxes for the risk panel (Twelve Data, falling back to FRED's daily closes), plus VIX and the
    US 10-year yield."""
    from app.services.daily_moves import _last_two, _pct, symbol_changes, ten_year

    sym = symbol_changes(db, back)
    out = []
    for s, label in TILES:
        if s in sym:
            out.append({"symbol": s, "label": label, "price": sym[s]["price"],
                        "change_1d_pct": sym[s]["change_pct"], "source": sym[s]["source"]})
    vix = _last_two(db, "vix", back)
    if vix:
        out.append({"symbol": "VIX", "label": "VIX", "price": vix[1], "change_1d_pct": _pct(vix),
                    "source": "FRED (daily)"})
    ty = ten_year(db, back)
    if ty:
        out.append({"symbol": "US10Y", "label": "US 10Y yield", "price": ty["yield"], "unit": "%",
                    "change_bps": ty["change_bps"], "source": "FRED (daily)"})
    return out


@router.get("/seasonality")
def seasonality_overview(years: int = 10, view: str = "monthly", db: Session = Depends(get_db)):
    """Average move and win rate for every asset by calendar month (view=monthly) or for the next four weeks
    (view=weekly), plus the seasonal leaders."""
    from app.services import seasonality as ss

    if view not in ("monthly", "weekly"):
        raise HTTPException(422, "view must be monthly or weekly")
    return ss.overview(db, max(3, min(years, 25)), view=view)


@router.get("/seasonality/{key}")
def seasonality_asset(key: str, years: int = 10, db: Session = Depends(get_db)):
    from app.services import seasonality as ss

    try:
        return ss.asset_view(db, key.upper(), max(3, min(years, 25)))
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.get("/macro/heatmap")
def macro_heatmap(currency: str = "USD", db: Session = Depends(get_db)):
    """Economic heatmap for one currency: latest releases with surprise, currency and stocks impact."""
    from app.services import heatmap as hm

    try:
        return hm.heatmap(db, currency)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


@router.get("/market-reaction")
def reactions(limit: int = 20, db: Session = Depends(get_db)):
    return rows(db.scalars(select(MarketReaction).order_by(MarketReaction.event_time.desc()).limit(limit)))
