"""Economic release analysis: surprise engine node and the Economic Event Report
(Sections 28-29, 57)."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import surprise as sx
from app.core.verification import badge
from app.models import (
    EconomicEvent,
    EconomicRelease,
    EconomicSurprise,
    ForecastError,
    Indicator,
    MarketReaction,
    PolicyScore,
)
from app.services import data_access as da
from app.services.audit import alert
from app.services.recompute import Context, node


def releases_in_scope(db: Session, ctx: Context) -> list[EconomicRelease]:
    rels: list[EconomicRelease] = []
    for rid in ctx.release_ids:
        r = db.get(EconomicRelease, rid)
        if r is not None:
            rels.append(r)
    for iid in ctx.indicator_ids:
        r = da.latest_current(db, iid)
        if r is not None and r not in rels:
            rels.append(r)
    return rels


def compute_surprise(db: Session, rel: EconomicRelease) -> EconomicSurprise | None:
    ind = db.get(Indicator, rel.indicator_id)
    db.execute(delete(EconomicSurprise).where(EconomicSurprise.release_id == rel.id))
    if not rel.is_current:
        return None
    ev = db.get(EconomicEvent, rel.event_id) if rel.event_id else None
    consensus = rel.consensus if rel.consensus is not None else (ev.consensus if ev else None)
    projection = None
    if ind.projection_variable and ind.central_bank_code:
        cb = da.cb_by_code(db, ind.central_bank_code)
        if cb:
            pr = da.projection_for(db, cb.id, ind.projection_variable, rel.reference_period[:4], rel.released_at)
            projection = pr[0].value if pr else None
    past = [s.market_surprise for s in db.scalars(
        select(EconomicSurprise).where(EconomicSurprise.indicator_id == ind.id,
                                       EconomicSurprise.release_id != rel.id))
            if s.market_surprise is not None]
    series = [r.actual for r in da.current_series(db, ind.id, 36)]
    changes = [b - a for a, b in zip(series[:-1], series[1:])]
    res = sx.evaluate(rel.actual, consensus, projection, past, changes, ind.unit, ind.transform, ind.higher_is)
    row = EconomicSurprise(release_id=rel.id, indicator_id=ind.id, market_surprise=res.market_surprise,
                           cb_surprise=res.cb_surprise, historical_z=res.historical_z,
                           classification=res.classification, policy_direction=res.policy_direction)
    db.add(row)
    return row


@node("surprise", triggers=("release", "full"), label="Economic surprise")
def surprise_node(db: Session, ctx: Context) -> None:
    for rel in releases_in_scope(db, ctx):
        s = compute_surprise(db, rel)
        if s is None:
            continue
        ind = db.get(Indicator, rel.indicator_id)
        ctx.currencies.add(ind.currency)
        if ind.central_bank_code:
            ctx.central_banks.add(ind.central_bank_code)
        unit = {"%": "%", "k": "k"}.get(ind.unit, "")
        cons = f" vs {rel.consensus:g}{unit} expected" if rel.consensus is not None else ""
        ctx.change(f"{ind.name} {rel.actual:g}{unit}{cons}: {s.classification}.")
        if s.historical_z is not None and abs(s.historical_z) >= 1 and ind.importance == "high":
            alert(db, "economic_surprise", f"{ind.name}: {s.classification}",
                  f"Actual {rel.actual:g}{unit}{cons} (z={s.historical_z:+.1f}). Policy direction: "
                  f"{s.policy_direction}. Data status: {badge(rel.verification_status, rel.confirmation_basis)}.",
                  "HIGH" if abs(s.historical_z) >= 2 else "MEDIUM", entity="economic_release", entity_id=rel.id,
                  currency=ind.currency, central_bank_code=ind.central_bank_code)


def event_report(db: Session, release_id: int) -> dict:
    """Economic Event Report (Section 29 / 57)."""
    from app.engines import scenario_engine
    from app.engines.forecast_engine import accuracy_summary
    from app.engines.market_engine import repricing_around, yields_around

    rel = db.get(EconomicRelease, release_id)
    if rel is None:
        raise LookupError("Release not found")
    ind = db.get(Indicator, rel.indicator_id)
    ev = db.get(EconomicEvent, rel.event_id) if rel.event_id else None
    s = db.scalar(select(EconomicSurprise).where(EconomicSurprise.release_id == rel.id))
    fe = db.scalar(select(ForecastError).where(ForecastError.release_id == rel.id,
                                               ForecastError.basis == "real_time"))
    cb = da.cb_by_code(db, ind.central_bank_code) if ind.central_bank_code else None
    unit = ind.unit
    status = badge(rel.verification_status, rel.confirmation_basis, rel.source_name)
    revisions = [{"revision": r.revision_number, "value": r.actual, "status": r.verification_status,
                  "current": r.is_current} for r in da.releases_for_period(db, ind.id, rel.reference_period)]
    what = (f"{ind.name} for {rel.reference_period} came in at {rel.actual:g}{unit}"
            + (f", previous {rel.previous:g}{unit}" if rel.previous is not None else "") + ".")
    expected = "No consensus forecast recorded."
    if s and s.market_surprise is not None:
        expected = (f"Consensus was {rel.consensus:g}{unit}; surprise {s.market_surprise:+.2f}{unit} "
                    f"({s.classification}" + (f", z={s.historical_z:+.1f}" if s.historical_z is not None else "")
                    + ").")
    consistent = "No central-bank projection is published for this indicator."
    if fe and fe.cb_projection is not None:
        consistent = (f"{cb.short_name if cb else 'The central bank'} projected {fe.cb_projection:g}{unit} for "
                      f"{rel.reference_period[:4]}; the actual is {fe.cb_error:+.2f} pp vs projection "
                      f"({fe.cb_classification}).")
    policy = None
    if cb:
        scores = list(db.scalars(select(PolicyScore).where(PolicyScore.central_bank_id == cb.id)
                                 .order_by(PolicyScore.as_of.desc()).limit(2)))
        if scores:
            p = scores[0]
            policy = {"central_bank": cb.code, "score": p.score, "classification": p.classification,
                      "previous": p.previous_score, "shift": p.shift, "shift_classification": p.shift_classification,
                      "explanation": p.explanation}
    reaction = db.scalar(select(MarketReaction).where(MarketReaction.event_entity == "release",
                                                      MarketReaction.event_id == rel.id))
    related_assets = [a for a in scenario_engine.tracked_assets(db) if ind.currency in (a[:3], a[3:])][:3]
    scen = {a: scenario_engine.latest_scenarios(db, a) for a in related_assets}
    invalidation = sorted({t["description"] for a in scen.values() for sc in a for t in sc.get("triggers", [])
                           if t["trigger_type"] == "invalidation"})[:6]
    return {
        "event": {"indicator": ind.code, "name": ind.name, "country": ind.country, "currency": ind.currency,
                  "reference_period": rel.reference_period, "released_at": rel.released_at,
                  "importance": ind.importance},
        "previous": rel.previous, "market_forecast": rel.consensus if rel.consensus is not None
        else (ev.consensus if ev else None),
        "central_bank_projection": fe.cb_projection if fe else None, "actual": rel.actual, "unit": unit,
        "data_status": {"status": rel.verification_status, "badge": status, "input_method": rel.input_method},
        "revisions": revisions,
        "market_surprise": s.market_surprise if s else None, "central_bank_surprise": s.cb_surprise if s else None,
        "historical_z": s.historical_z if s else None, "classification": s.classification if s else None,
        "policy_direction": s.policy_direction if s else None,
        "three_way": {"central_bank": fe.cb_projection, "market": fe.market_forecast, "actual": fe.actual,
                      "cb_error": fe.cb_error, "market_error": fe.market_error,
                      "more_accurate": fe.more_accurate} if fe else None,
        "forecast_accuracy": accuracy_summary(db, cb.code, ind.projection_variable) if cb and
        ind.projection_variable else None,
        "why_forecast_missed": fe.miss_explanation if fe and fe.miss_explanation else None,
        "narrative": {"what_happened": what, "was_it_expected": expected, "consistent_with_projection": consistent},
        "policy_implication": policy,
        "rate_expectation_change": repricing_around(db, cb.code, rel.released_at) if cb and rel.released_at else None,
        "bond_market_reaction": yields_around(db, ind.currency, rel.released_at) if rel.released_at else None,
        "fx_and_asset_reaction": {"windows": reaction.windows, "expected": reaction.expected,
                                  "divergences": reaction.divergences} if reaction else None,
        "scenarios": scen, "invalidation": invalidation,
    }

