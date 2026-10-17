"""Home dashboard, alerts, watchlists, recompute and AI endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import search as ai_search
from app.api.deps import Auth, current_user_id, get_db, row, rows
from app.engines import cb_engine, currency_engine, market_engine, research_engine, trading_engine
from app.models import (
    Alert,
    EconomicRelease,
    EconomicSurprise,
    ForecastError,
    Indicator,
    MacroRegime,
    PolicyScore,
    RecomputeJob,
    Watchlist,
)
from app.services import recompute, verification_service

router = APIRouter(prefix="/api", tags=["system"], dependencies=[Auth])


class WatchIn(BaseModel):
    asset: str
    note: str | None = None
    alert_on_bias_change: bool = True


class AskIn(BaseModel):
    question: str


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    regime = db.scalar(select(MacroRegime).order_by(MacroRegime.as_of.desc(), MacroRegime.id.desc()))
    surprises = []
    for s, rel, ind in db.execute(select(EconomicSurprise, EconomicRelease, Indicator)
                                  .join(EconomicRelease, EconomicSurprise.release_id == EconomicRelease.id)
                                  .join(Indicator, EconomicSurprise.indicator_id == Indicator.id)
                                  .where(EconomicSurprise.historical_z.is_not(None))
                                  .order_by(EconomicSurprise.created_at.desc()).limit(40)):
        surprises.append({"indicator": ind.name, "currency": ind.currency, "period": rel.reference_period,
                          "actual": rel.actual, "consensus": rel.consensus, "z": s.historical_z,
                          "classification": s.classification, "direction": s.policy_direction,
                          "release_id": rel.id, "status": rel.verification_status})
    surprises.sort(key=lambda x: -abs(x["z"] or 0))
    errors = []
    for fe, rel, ind in db.execute(select(ForecastError, EconomicRelease, Indicator)
                                   .join(EconomicRelease, ForecastError.release_id == EconomicRelease.id)
                                   .join(Indicator, ForecastError.indicator_id == Indicator.id)
                                   .where(ForecastError.basis == "real_time", ForecastError.cb_error.is_not(None),
                                          EconomicRelease.is_current.is_(True))
                                   .order_by(EconomicRelease.reference_period.desc()).limit(40)):
        if any(e["indicator"] == ind.name for e in errors):
            continue  # latest period per indicator
        errors.append({"indicator": ind.name, "period": rel.reference_period, "cb_projection": fe.cb_projection,
                       "actual": fe.actual, "error": fe.cb_error, "classification": fe.cb_classification})
    shifts = []
    seen = set()
    for p in db.scalars(select(PolicyScore).order_by(PolicyScore.as_of.desc()).limit(100)):
        if p.central_bank_id in seen:
            continue
        seen.add(p.central_bank_id)
        if p.shift is not None and abs(p.shift) >= 3:
            shifts.append({"central_bank_id": p.central_bank_id, "score": p.score, "shift": p.shift,
                           "classification": p.shift_classification})
    health = verification_service.data_health(db)
    return {
        "regime": row(regime), "central_bank_heatmap": cb_engine.heatmap(db),
        "currency_strength": currency_engine.currency_heatmap(db),
        "currency_scores": [row(s) for s in sorted(currency_engine.latest_scores(db).values(),
                                                    key=lambda s: -s.total)],
        "biggest_surprises": surprises[:8], "forecast_errors": errors, "policy_shifts": shifts,
        "yields": market_engine.yields_overview(db), "rates": market_engine.rates_overview(db),
        "top_setups": trading_engine.top_setups(db, 6), "market_wrong": research_engine.market_wrong_checks(db),
        "alerts": rows(db.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(8))),
        "data_health": {k: health[k] for k in ("overall", "manual_records", "unverified", "user_confirmed_awaiting",
                                               "conflicts")} | {"missing_scheduled": len(health["missing_scheduled"]),
                                                                "failing_sources": [s["key"] for s in health["sources"]
                                                                                    if s["needs_manual_input"]]},
        "ai_summary": _summary(db, regime),
    }


def _summary(db: Session, regime) -> str:
    parts = []
    if regime:
        parts.append(f"Global regime: {regime.primary}" + (f" / {regime.secondary}" if regime.secondary else "") +
                     f" (confidence {regime.confidence:.0f}%).")
    scores = sorted(currency_engine.latest_scores(db).values(), key=lambda s: -s.total)
    if scores:
        parts.append(f"Strongest fundamentals: {scores[0].currency} ({scores[0].total:+.0f}); weakest: "
                     f"{scores[-1].currency} ({scores[-1].total:+.0f}).")
    setups = [s for s in trading_engine.top_setups(db, 3) if s["grade"] != "NO TRADE"]
    if setups:
        parts.append("Highest-conviction setups: " + ", ".join(f"{s['asset']} {s['direction'].lower()} "
                                                               f"({s['grade']})" for s in setups) + ".")
    else:
        parts.append("No setup currently meets the confluence threshold — NO TRADE is the default.")
    return " ".join(parts) or "Not enough data yet. Run ingestion or add data manually."


@router.get("/alerts")
def alerts(unread: bool = False, kind: str | None = None, limit: int = 100, db: Session = Depends(get_db)):
    q = select(Alert).order_by(Alert.created_at.desc()).limit(limit)
    if unread:
        q = q.where(Alert.is_read.is_(False))
    if kind:
        q = q.where(Alert.kind == kind)
    return {"alerts": rows(db.scalars(q)),
            "unread": db.scalar(select(func.count(Alert.id)).where(Alert.is_read.is_(False)))}


@router.get("/notifications")
def notifications_status(db: Session = Depends(get_db)):
    from app.services import notify

    return notify.status(db)


@router.post("/notifications/test")
def notifications_test():
    from app.services import notify

    ok, err = notify.send_telegram("✅ <b>Mac Fundamental Intelligence</b>\nPhone alerts are working.")
    if not ok:
        raise HTTPException(400, err)
    return {"sent": True}


@router.post("/alerts/{alert_id}/read")
def mark_read(alert_id: int, db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(404, "Alert not found")
    a.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/alerts/read-all")
def read_all(db: Session = Depends(get_db)):
    for a in db.scalars(select(Alert).where(Alert.is_read.is_(False))):
        a.is_read = True
    db.commit()
    return {"ok": True}


@router.get("/watchlist")
def watchlist(db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    out = []
    for w in db.scalars(select(Watchlist).where(Watchlist.user_id == user_id)):
        s = trading_engine.latest_setup(db, w.asset)
        out.append({**row(w), "grade": s.grade if s else None, "direction": s.direction if s else None,
                    "confluence": s.confluence_score if s else None, "data_status": s.data_status if s else None})
    return out


@router.post("/watchlist")
def add_watch(body: WatchIn, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    asset = body.asset.upper().replace("/", "")
    w = Watchlist(user_id=user_id, asset=asset, note=body.note, alert_on_bias_change=body.alert_on_bias_change)
    db.add(w)
    db.commit()
    return row(w)


@router.delete("/watchlist/{wid}")
def del_watch(wid: int, db: Session = Depends(get_db)):
    w = db.get(Watchlist, wid)
    if w is None:
        raise HTTPException(404, "Not found")
    db.delete(w)
    db.commit()
    return {"ok": True}


@router.post("/recompute/{entity}")
def run_recompute(entity: str, entity_id: int | None = None, db: Session = Depends(get_db)):
    if entity not in recompute.TRIGGERS and entity != "full":
        recompute._load_engines()
        if entity not in recompute.TRIGGERS:
            raise HTTPException(404, f"Unknown trigger '{entity}'. Known: {sorted(recompute.TRIGGERS)}")
    job = recompute.trigger(db, entity, entity_id)
    return row(job)


@router.get("/recompute/graph")
def graph():
    recompute._load_engines()
    return {"nodes": recompute.graph(), "triggers": dict(recompute.TRIGGERS)}


@router.get("/recompute/{job_id}")
def job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(RecomputeJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    return row(j)


@router.post("/ai/search")
def search(body: AskIn, db: Session = Depends(get_db)):
    return ai_search.search(db, body.question)


@router.post("/ai/analyze")
def analyze(body: AskIn, db: Session = Depends(get_db)):
    """Alias for search that always returns the full professional response format."""
    return ai_search.search(db, body.question)
