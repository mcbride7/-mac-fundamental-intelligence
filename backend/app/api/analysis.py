"""Fundamental analysis, scenarios, trade setups, forecast research (Phases 5-7)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Auth, get_db, rows
from app.engines import research_engine, scenario_engine, trading_engine
from app.engines.forecast_engine import forecastability_table
from app.models import ScenarioProbability, TradeSetup

router = APIRouter(prefix="/api", tags=["analysis"], dependencies=[Auth])


def _asset(a: str) -> str:
    a = a.upper().replace("/", "").replace("-", "")
    if not scenario_engine.is_fx_pair(a):
        raise HTTPException(422, "Use an FX pair such as EURUSD, USDJPY or USDZAR")
    return a


@router.get("/fundamental/{asset}")
def fundamental(asset: str, db: Session = Depends(get_db)):
    return trading_engine.analyse(db, _asset(asset))


@router.get("/scenarios/{asset}")
def scenarios(asset: str, db: Session = Depends(get_db)):
    a = _asset(asset)
    stored = scenario_engine.latest_scenarios(db, a)
    if not stored:
        res = scenario_engine.build_for_asset(db, a)
        stored = [s.__dict__ for s in res["scenarios"]]
    hist = rows(db.scalars(select(ScenarioProbability).where(ScenarioProbability.asset == a)
                           .order_by(ScenarioProbability.as_of.desc()).limit(80)))
    return {"asset": a, "scenarios": stored, "probability_method": scenario_engine.probability_method(),
            "history": hist}


@router.get("/track-record")
def track_record_summary(db: Session = Depends(get_db)):
    from app.services import track_record

    track_record.evaluate(db)
    return track_record.summary(db)


@router.get("/track-record/{signal_id}/setup")
def track_record_setup(signal_id: int, db: Session = Depends(get_db)):
    """One call's chart data and the setup behind it, as it stood when the call was given."""
    from app.services import track_record

    try:
        return track_record.setup_detail(db, signal_id)
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.get("/track-record/{signal_id}/chart")
def track_record_chart(signal_id: int, db: Session = Depends(get_db)):
    """4-hour candles for one call with the strategy's zone, entry, stop and target (or the zones it's waiting on)."""
    from datetime import datetime

    from app.models.track import SignalRecord
    from app.services import track_record
    from app.strategy import sd_live

    rec = db.get(SignalRecord, signal_id)
    if rec is None:
        raise HTTPException(404, "No such call")
    sd = track_record.sd_for(db, rec)
    around = end = None
    if sd and sd.get("zone"):
        around = datetime.fromisoformat(sd["zone"]["from"])
        end = datetime.fromisoformat(sd["exit_at"]) if sd.get("exit_at") else None
    return {"asset": rec.asset, "direction": rec.direction, "opened_at": track_record._aware(rec.opened_at).isoformat(),
            "call_price": rec.entry_price, "sd": sd, "candles": sd_live.chart(db, rec.asset, around, end)}


@router.patch("/track-record/{signal_id}")
def track_record_edit(signal_id: int, body: dict, db: Session = Depends(get_db)):
    """Change a call's trade type (swing / day), stop loss or take profit."""
    from app.services import track_record

    def _f(k):
        v = body.get(k)
        return None if v in (None, "") else float(v)
    try:
        return track_record.edit_plan(db, signal_id, body.get("trade_type") or None, _f("stop_loss"), _f("take_profit"))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))


@router.get("/trade-setups")
def setups(db: Session = Depends(get_db)):
    return trading_engine.top_setups(db, 50)


@router.get("/trade-setups/{asset}/history")
def setup_history(asset: str, db: Session = Depends(get_db)):
    return rows(db.scalars(select(TradeSetup).where(TradeSetup.asset == _asset(asset))
                           .order_by(TradeSetup.as_of.desc()).limit(50)))


@router.get("/forecast-accuracy")
def rankings(variable: str | None = None, basis: str = "real_time", window: str = "5y",
             db: Session = Depends(get_db)):
    return research_engine.forecast_rankings(db, variable, basis, window)


@router.get("/forecastability")
def forecastability(db: Session = Depends(get_db)):
    return forecastability_table(db)


@router.get("/research/market-wrong")
def market_wrong(db: Session = Depends(get_db)):
    return research_engine.market_wrong_checks(db)


@router.get("/research/historical/{asset}")
def historical(asset: str, k: int = 5, db: Session = Depends(get_db)):
    return research_engine.historical_analogues(db, _asset(asset), k)


@router.get("/research/event-study")
def event_study(central_bank: str, variable: str = "inflation", condition: str = "above", asset: str | None = None,
                db: Session = Depends(get_db)):
    try:
        return research_engine.event_study(db, central_bank.upper(), variable, condition, asset)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
