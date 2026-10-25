"""Macro regime and currency fundamental scores (Sections 34-35, 46)."""
from __future__ import annotations

import statistics
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import currency as cx
from app.analytics import regime as rx
from app.db import utcnow
from app.engines import fundamentals as fnd
from app.ingestion.markets import price_at
from app.models import CurrencyScore, MacroRegime, MarketPrice, PolicyScore
from app.services import data_access as da
from app.services.audit import alert
from app.services.recompute import Context, node

MAJORS = ["US", "EA", "GB", "JP", "CA", "AU"]


def _pct(db: Session, sym: str, days: int) -> float | None:
    last = db.scalar(select(MarketPrice).where(MarketPrice.symbol == sym).order_by(MarketPrice.ts.desc()))
    if not last:
        return None
    old = price_at(db, sym, last.ts - timedelta(days=days))
    if not old or old.ts >= last.ts or not old.price:
        return None
    return (last.price / old.price - 1) * 100


def regime_inputs(db: Session) -> rx.RegimeInputs:
    trends, gaps = [], []
    for c in MAJORS:
        ind, rel = da.latest_by_code(db, fnd.HEADLINE_INFL[c])
        if rel is None:
            continue
        s = da.current_series(db, ind.id, 8)
        if len(s) >= 4:
            trends.append(s[-1].actual - s[max(0, len(s) - 7)].actual)
        cb = da.cb_by_code(db, ind.central_bank_code) if ind.central_bank_code else None
        if cb and cb.inflation_target is not None:
            gaps.append(rel.actual - cb.inflation_target)
    growth, neg = [], []
    for c, code in fnd.PMI.items():
        _, rel = da.latest_by_code(db, code)
        if rel:
            growth.append(max(-1, min(1, (rel.actual - 50) / 5)))
    for c, code in fnd.GDP.items():
        ind, rel = da.latest_by_code(db, code)
        if rel:
            trend = 1.8 if ind.transform == "qoq_saar" else 0.4
            growth.append(max(-1, min(1, (rel.actual - trend) / (2 * trend))))
            neg.append(1 if rel.actual < 0 else 0)
    from app.services.risk_sentiment import latest_reading

    risk = latest_reading(db)
    if risk is not None and risk.score is None:
        risk = None
    eq = _pct(db, "SPX", 50)
    gold = _pct(db, "XAUUSD", 30)
    jpy, chf = _pct(db, "USDJPY", 30), _pct(db, "USDCHF", 30)
    havens = [-x for x in (jpy, chf) if x is not None]
    changes = []
    since = utcnow() - timedelta(days=90)
    for cb_id in {p.central_bank_id for p in db.scalars(select(PolicyScore))}:
        latest = db.scalar(select(PolicyScore).where(PolicyScore.central_bank_id == cb_id)
                           .order_by(PolicyScore.as_of.desc()))
        old = db.scalar(select(PolicyScore).where(PolicyScore.central_bank_id == cb_id, PolicyScore.as_of <= since)
                        .order_by(PolicyScore.as_of.desc()))
        if latest and old:
            changes.append(latest.score - old.score)
    return rx.RegimeInputs(
        inflation_trend=statistics.fmean(trends) if trends else None,
        inflation_gap=statistics.fmean(gaps) if gaps else None,
        growth_signal=statistics.fmean(growth) if growth else None,
        negative_gdp_share=statistics.fmean(neg) if neg else None,
        equity_trend=eq, gold_trend=gold, safe_haven_fx=statistics.fmean(havens) if havens else None,
        risk_label=risk.label if risk else None, risk_score=risk.score if risk else None,
        policy_score_change=statistics.fmean(changes) if changes else None)


@node("macro_regime", depends_on=("policy_score", "yield_curves"), triggers=("market_data", "full"),
      label="Macro regime")
def macro_regime_node(db: Session, ctx: Context) -> None:
    res = rx.evaluate(regime_inputs(db))
    prev = fnd.latest_regime(db)
    db.add(MacroRegime(primary=res.primary, secondary=res.secondary, confidence=res.confidence,
                       signals=res.signals, explanation=res.explanation))
    if prev is None or prev.primary != res.primary or prev.secondary != res.secondary:
        ctx.change(f"Macro regime: {res.primary}" + (f" / {res.secondary}" if res.secondary else "") + ".")
        if prev is not None:
            alert(db, "regime_change", f"Macro regime changed to {res.primary}",
                  f"Previously {prev.primary}. " + "; ".join(res.explanation), "MEDIUM", entity="macro_regime")


def score_currency(db: Session, ccy: str, snaps: dict[str, fnd.Snapshot], regime: MacroRegime | None
                   ) -> tuple[cx.CurrencyScoreResult, fnd.Snapshot]:
    s = snaps[ccy]
    rates = [x.policy_rate for x in snaps.values() if x.policy_rate is not None]
    y2s = [x.y2 for x in snaps.values() if x.y2 is not None]
    dev = s.deviations
    inp = cx.CurrencyInputs(
        currency=ccy, policy_score=s.policy_score, policy_rate=s.policy_rate,
        avg_policy_rate=statistics.fmean(rates) if len(rates) >= 3 else None,
        implied_change_bps=s.implied_change_bps, inflation=s.inflation, inflation_target=s.inflation_target,
        inflation_vs_projection=dev.get("core_inflation", dev.get("inflation")),
        growth_vs_projection=dev.get("gdp"), gdp_latest=s.gdp_latest, pmi=s.pmi,
        unemployment_change_6m=s.unemployment_change_6m, y2=s.y2,
        y2_change_1m_bps=s.y2_change_1m_bps, avg_y2=statistics.fmean(y2s) if len(y2s) >= 3 else None,
        surprise_index=s.surprise_index,
        risk_regime=("Risk-Off" if regime and (regime.secondary or "").upper() == "RISK-OFF" else
                     "Risk-On" if regime and (regime.secondary or "").upper() == "RISK-ON" else None),
        evidence_quality=s.evidence_quality)
    return cx.score(inp), s


@node("currency_scores", depends_on=("policy_score", "macro_regime", "surprise", "policy_divergence"),
      triggers=("full",), label="Currency scores")
def currency_scores_node(db: Session, ctx: Context) -> None:
    snaps = fnd.build_all(db)
    regime = fnd.latest_regime(db)
    for ccy in fnd.CURRENCIES:
        res, s = score_currency(db, ccy, snaps, regime)
        prev = db.scalar(select(CurrencyScore).where(CurrencyScore.currency == ccy)
                         .order_by(CurrencyScore.as_of.desc(), CurrencyScore.id.desc()))
        db.add(CurrencyScore(currency=ccy, components=res.components, total=res.total, bias=res.bias,
                             evidence_quality=s.evidence_quality, previous_total=prev.total if prev else None,
                             data_status={"coverage": res.coverage, "notes": res.notes,
                                          "manual_inputs": sum(1 for x in s.sources
                                                               if x["input_method"] != "automated")}))
        ctx.metrics[f"CCY:{ccy}"] = res.total
        if prev is not None and prev.total != res.total and (ccy in ctx.currencies or abs(prev.total - res.total) >= 2):
            ctx.change(f"{ccy} score {prev.total:+.0f} → {res.total:+.0f}.")
        if prev is not None and prev.bias != res.bias:
            alert(db, "bias_change", f"{ccy} fundamental bias {prev.bias} → {res.bias}",
                  f"Score {prev.total:+.0f} → {res.total:+.0f}. Components: {res.components}", "MEDIUM",
                  entity="currency_score", currency=ccy)


def latest_scores(db: Session) -> dict[str, CurrencyScore]:
    out = {}
    for ccy in fnd.CURRENCIES:
        r = db.scalar(select(CurrencyScore).where(CurrencyScore.currency == ccy)
                      .order_by(CurrencyScore.as_of.desc(), CurrencyScore.id.desc()))
        if r:
            out[ccy] = r
    return out


def currency_heatmap(db: Session) -> dict:
    scores = latest_scores(db)
    return cx.heatmap({c: s.total for c, s in scores.items()})
