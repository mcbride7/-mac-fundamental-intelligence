"""Scenario engine (Phase 5): base / bullish / bearish / risk scenarios per asset,
with transparent probabilities and activation / confirmation / invalidation
conditions that are re-evaluated on every recompute."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import scenarios as scx
from app.analytics import trading as tx
from app.db import utcnow
from app.engines import fundamentals as fnd
from app.models import (
    CentralBankMeeting,
    CurrencyScore,
    EconomicEvent,
    EconomicRelease,
    Indicator,
    Scenario,
    ScenarioProbability,
    ScenarioTrigger,
    Watchlist,
)
from app.services import data_access as da
from app.services.audit import alert
from app.services.recompute import Context, node

DEFAULT_ASSETS = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD", "USDZAR", "USDMXN",
                  "EURGBP", "EURJPY"]


def is_fx_pair(asset: str) -> bool:
    return len(asset) == 6 and asset[:3] in fnd.COUNTRY and asset[3:] in fnd.COUNTRY


def tracked_assets(db: Session) -> list[str]:
    extra = [w.asset.upper().replace("/", "") for w in db.scalars(select(Watchlist))]
    return list(dict.fromkeys(DEFAULT_ASSETS + [a for a in extra if is_fx_pair(a)]))


def side(db: Session, snap: fnd.Snapshot, score: CurrencyScore | None) -> tx.Side:
    comp = score.components if score else {}
    dev = snap.deviations
    from app.analytics.forecast import policy_implication

    fd = policy_implication(dev)["score"] if dev else None
    return tx.Side(
        currency=snap.currency, cb_code=snap.cb.code if snap.cb else None, policy_score=snap.policy_score,
        policy_confidence=snap.policy_confidence, policy_rate=snap.policy_rate,
        implied_change_bps=snap.implied_change_bps,
        inflation_gap=(snap.inflation - snap.inflation_target) if snap.inflation is not None and
        snap.inflation_target is not None else None,
        growth_component=comp.get("growth"), employment_component=comp.get("employment"),
        y2=snap.y2, y2_change_1m_bps=snap.y2_change_1m_bps, surprise_index=snap.surprise_index,
        risk_component=comp.get("risk_sentiment"), forecast_deviation=fd)


def pair_inputs(db: Session, asset: str, snaps: dict | None = None) -> tuple[tx.Side, tx.Side, fnd.Snapshot,
                                                                            fnd.Snapshot]:
    from app.engines.currency_engine import latest_scores

    b, q = asset[:3], asset[3:]
    snaps = snaps or {}
    sb = snaps.get(b) or fnd.build(db, b)
    sq = snaps.get(q) or fnd.build(db, q)
    scores = latest_scores(db)
    return side(db, sb, scores.get(b)), side(db, sq, scores.get(q)), sb, sq


def catalysts(db: Session, currencies: list[str], days: int = 14) -> list[dict]:
    now = utcnow()
    out = []
    rows = db.execute(select(EconomicEvent, Indicator).join(Indicator, EconomicEvent.indicator_id == Indicator.id)
                      .where(Indicator.currency.in_(currencies), EconomicEvent.scheduled_at > now,
                             EconomicEvent.scheduled_at <= now + timedelta(days=days))
                      .order_by(EconomicEvent.scheduled_at)).all()
    for ev, ind in rows:
        if db.scalar(select(EconomicRelease.id).where(EconomicRelease.event_id == ev.id)):
            continue
        out.append({"name": f"{ind.name} ({ev.reference_period})", "date": ev.scheduled_at.strftime("%Y-%m-%d %H:%M"),
                    "currency": ind.currency, "importance": ind.importance,
                    "hours_until": round((fnd._aware(ev.scheduled_at) - now).total_seconds() / 3600, 1),
                    "consensus": ev.consensus})
    for ccy in currencies:
        cb = da.cb_by_currency(db, ccy)
        if cb is None:
            continue
        m = db.scalar(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id,
                                                       CentralBankMeeting.meeting_date >= now.date(),
                                                       CentralBankMeeting.meeting_date <= (now + timedelta(days=days))
                                                       .date()).order_by(CentralBankMeeting.meeting_date))
        if m:
            out.append({"name": f"{cb.short_name} policy decision", "date": m.meeting_date.isoformat(),
                        "currency": ccy, "importance": "high",
                        "hours_until": (m.meeting_date - now.date()).days * 24.0,
                        "expected": m.expected_decision})
    imp = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda x: (x.get("hours_until") or 0, imp.get(x["importance"], 3)))
    return out


def metrics_for(db: Session, b: str, q: str, sb: fnd.Snapshot, sq: fnd.Snapshot) -> dict:
    m = {}
    for s in (sb, sq):
        if s.cb and s.policy_score is not None:
            m[f"POLICY:{s.cb.code}"] = s.policy_score
        if s.inflation is not None:
            m[f"INFL:{s.currency}"] = s.inflation
    if sb.y2 is not None and sq.y2 is not None:
        m[f"SPREAD2Y:{b}-{q}"] = round(sb.y2 - sq.y2, 3)
    return m


def build_for_asset(db: Session, asset: str, snaps: dict | None = None) -> dict:
    sbase, squote, sb, sq = pair_inputs(db, asset, snaps)
    conf = tx.confluence(sbase, squote)
    regime = fnd.latest_regime(db)
    b, q = asset[:3], asset[3:]
    ctx = scx.ScenarioContext(asset=asset, base_ccy=b, quote_ccy=q, base_cb=sb.cb.short_name if sb.cb else None,
                              quote_cb=sq.cb.short_name if sq.cb else None, confluence_total=conf.total,
                              factors=conf.factors, regime_secondary=regime.secondary if regime else None,
                              metrics=metrics_for(db, b, q, sb, sq), catalysts=catalysts(db, [b, q]))
    # trigger metric keys use CB codes; scenario titles use short names
    ctx.base_cb, ctx.quote_cb = (sb.cb.code if sb.cb else None), (sq.cb.code if sq.cb else None)
    scen = scx.build(ctx)
    return {"confluence": conf, "scenarios": scen, "metrics": ctx.metrics, "catalysts": ctx.catalysts,
            "snapshots": (sb, sq), "sides": (sbase, squote)}


@node("scenarios", depends_on=("currency_scores", "policy_divergence", "market_reaction"), triggers=("full",),
      label="Scenarios")
def scenarios_node(db: Session, ctx: Context) -> None:
    snaps = fnd.build_all(db)
    for asset in tracked_assets(db):
        if ctx.currencies and asset[:3] not in ctx.currencies and asset[3:] not in ctx.currencies \
                and ctx.trigger_entity not in ("full", "market_data"):
            continue
        res = build_for_asset(db, asset, snaps)
        prev_base = db.scalar(select(ScenarioProbability).where(ScenarioProbability.asset == asset,
                                                                ScenarioProbability.kind == "base")
                              .order_by(ScenarioProbability.as_of.desc()))
        old_ids = [s.id for s in db.scalars(select(Scenario).where(Scenario.asset == asset))]
        if old_ids:
            db.execute(delete(ScenarioTrigger).where(ScenarioTrigger.scenario_id.in_(old_ids)))
            db.execute(delete(Scenario).where(Scenario.id.in_(old_ids)))
        for s in res["scenarios"]:
            row = Scenario(asset=asset, kind=s.kind, title=s.title, narrative=s.narrative, direction=s.direction,
                           probability=s.probability, drivers=s.drivers,
                           activation=[t for t in s.triggers if t["trigger_type"] == "activation"],
                           confirmation=[t for t in s.triggers if t["trigger_type"] == "confirmation"],
                           invalidation=[t for t in s.triggers if t["trigger_type"] == "invalidation"],
                           evidence=s.evidence)
            db.add(row)
            db.flush()
            for t in s.triggers:
                db.add(ScenarioTrigger(scenario_id=row.id, trigger_type=t["trigger_type"],
                                       description=t["description"], metric=t.get("metric"),
                                       operator=t.get("operator"), threshold=t.get("threshold"),
                                       status=scx.evaluate_trigger(t, res["metrics"])))
            db.add(ScenarioProbability(asset=asset, kind=s.kind, probability=s.probability))
        base = res["scenarios"][0]
        if prev_base is not None and abs(base.probability - prev_base.probability) >= 10:
            alert(db, "scenario_probability", f"{asset}: base-case probability {prev_base.probability:.0f}% → "
                                              f"{base.probability:.0f}%", base.title, "MEDIUM", entity="scenario")
            ctx.change(f"{asset} base case probability {prev_base.probability:.0f}% → {base.probability:.0f}%.")


def latest_scenarios(db: Session, asset: str) -> list[dict]:
    rows = list(db.scalars(select(Scenario).where(Scenario.asset == asset).order_by(Scenario.id)))
    out = []
    for s in rows:
        trig = [{"trigger_type": t.trigger_type, "description": t.description, "metric": t.metric,
                 "operator": t.operator, "threshold": t.threshold, "status": t.status}
                for t in db.scalars(select(ScenarioTrigger).where(ScenarioTrigger.scenario_id == s.id))]
        out.append({"kind": s.kind, "title": s.title, "narrative": s.narrative, "direction": s.direction,
                    "probability": s.probability, "drivers": s.drivers, "triggers": trig, "evidence": s.evidence,
                    "as_of": s.as_of})
    return out


def probability_method() -> str:
    return ("Probabilities: risk scenario 12% (20% in a risk-off regime). The remaining mass is split by "
            "p = 0.5 + 0.35·tanh(|confluence|/40) between the favoured direction (75% base case, 25% extension) "
            "and the opposite direction (1 − p).")
