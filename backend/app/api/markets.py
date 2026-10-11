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
    hist = rows(db.scalars(select(MacroRegime).order_by(MacroRegime.as_of.desc()).limit(30)))
    return {"current": row(cur), "history": hist}


@router.get("/market-reaction")
def reactions(limit: int = 20, db: Session = Depends(get_db)):
    return rows(db.scalars(select(MarketReaction).order_by(MarketReaction.event_time.desc()).limit(limit)))
