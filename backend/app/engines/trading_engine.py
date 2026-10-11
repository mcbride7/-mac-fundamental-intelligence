"""Trading intelligence (Phase 6): asset fundamental analysis, trade confluence,
trade bias, the NO-TRADE engine, verification caps, alerts and watchlists.

Decision support only: setups are never executed and never guaranteed."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import trading as tx
from app.core.enums import Grade, VerificationStatus
from app.core.verification import apply_cap, evidence_quality, grade_cap
from app.engines import fundamentals as fnd
from app.engines import scenario_engine as se
from app.models import FundamentalAnalysis, TradeBias, TradeSetup, Watchlist
from app.services.audit import alert
from app.services.recompute import Context, node

SAFETY = ("Decision-support research only. Not investment advice; no outcome is guaranteed and nothing is "
          "executed automatically.")


def analyse(db: Session, asset: str, snaps: dict | None = None) -> dict:
    """Full asset fundamental analysis in the professional response format (Section 59)."""
    from app.engines.market_engine import price_move

    asset = asset.upper().replace("/", "")
    if not se.is_fx_pair(asset):
        raise ValueError("Fundamental trade analysis currently supports FX pairs (e.g. EURUSD, USDJPY, USDZAR)")
    res = se.build_for_asset(db, asset, snaps)
    conf: tx.Confluence = res["confluence"]
    sb, sq = res["snapshots"]
    scen = res["scenarios"]
    b, q = asset[:3], asset[3:]
    points = sb.points + sq.points
    eq = evidence_quality(points) if points else 40.0
    cap, cap_reason, data_status = grade_cap(points)
    probs = {s.kind: s.probability for s in scen}
    base = scen[0]
    opp = next(s for s in scen[1:] if s.direction != base.direction and s.kind != "risk")
    gap = base.probability - opp.probability
    nt_in = tx.NoTradeInputs(
        pending_events=res["catalysts"],
        conflict=any(p.status == VerificationStatus.CONFLICT.value and p.critical for p in points),
        base_policy_confidence=sb.policy_confidence, quote_policy_confidence=sq.policy_confidence,
        scenario_gap=gap, price_move_20d_pct=price_move(db, asset), evidence_quality=eq,
        available_factors=len(conf.factors))
    reasons = tx.no_trade_reasons(conf, nt_in)
    g = tx.grade(conf.total, conf.agreement)
    if reasons:
        g = Grade.NO_TRADE
    g = apply_cap(g, cap)
    direction = conf.direction if g != Grade.NO_TRADE else "NONE"
    bias = "BULLISH" if conf.total >= 15 else "BEARISH" if conf.total <= -15 else "NEUTRAL"
    sorted_f = sorted(conf.factors.items(), key=lambda kv: -abs(kv[1]))
    aligned = [(k, v) for k, v in sorted_f if conf.total and (v > 0) == (conf.total > 0) and abs(v) >= 1]
    primary = tx.LABELS[aligned[0][0]] if aligned else None
    secondary = [tx.LABELS[k] for k, _ in aligned[1:4]]
    base_d = next(s for s in scen if s.kind == "base")
    confirmation = [t["description"] for t in base_d.triggers if t["trigger_type"] == "confirmation"]
    invalidation = [t["description"] for t in base_d.triggers if t["trigger_type"] == "invalidation"]
    risks = [f"{tx.LABELS[k]} points the other way ({v:+.0f})" for k, v in sorted_f
             if conf.total and (v > 0) != (conf.total > 0) and abs(v) >= 3][:3]
    if data_status != "All verified":
        risks.append(f"Data status: {data_status} — see Data Health")
    if sb.implied_is_proxy or sq.implied_is_proxy:
        risks.append("Rate expectations derived from the 2Y-yield proxy (no futures/OIS data supplied)")
    risks.append(f"Risk scenario ({probs.get('risk', 0):.0f}%): global risk-off shock")
    forecast_conf = round(min(sb.policy_confidence or 40, sq.policy_confidence or 40), 1)
    scenario_conf = round(min(95.0, 40 + abs(gap)), 1)
    research_alerts = []
    report = {
        "conclusion": _conclusion(asset, bias, g, conf, primary, reasons),
        "facts": [s for s in sb.sources + sq.sources],
        "market_expectation": {c.currency: {"prob_cut": c.prob_cut, "prob_hike": c.prob_hike,
                                            "implied_12m_change_bps": c.implied_change_bps,
                                            "proxy": c.implied_is_proxy} for c in (sb, sq)},
        "central_bank_projection": {c.currency: c.deviations for c in (sb, sq)},
        "what_changed": [], "why_it_matters": _why(conf, b, q),
        "policy_implication": {c.currency: {"policy_score": c.policy_score, "statement_tone": c.statement_tone}
                               for c in (sb, sq)},
        "market_impact": {"fx": f"{asset} bias {bias.lower()}",
                          "bonds": f"2Y spread {b}-{q}: {res['metrics'].get(f'SPREAD2Y:{b}-{q}')}"},
        "scenarios": [{"kind": s.kind, "title": s.title, "probability": s.probability, "direction": s.direction}
                      for s in scen],
        "confirmation": confirmation, "invalidation": invalidation,
        "trade_bias": None if g == Grade.NO_TRADE else {"direction": direction, "grade": g.value},
        "risk": risks, "disclaimer": SAFETY,
    }
    return {
        "asset": asset, "bias": bias, "direction": direction, "grade": g.value, "conviction": conf.conviction,
        "confluence_total": conf.total, "agreement": conf.agreement,
        "factors": {tx.LABELS[k]: v for k, v in conf.factors.items()},
        "unavailable_factors": [tx.LABELS[k] for k in conf.unavailable],
        "no_trade_reasons": reasons, "grade_cap": cap.value if cap else None, "grade_cap_reason": cap_reason,
        "data_status": data_status, "evidence_quality": eq, "forecast_confidence": forecast_conf,
        "scenario_confidence": scenario_conf, "time_horizon": "1–4 weeks", "primary_driver": primary,
        "secondary_drivers": secondary, "catalysts": res["catalysts"][:6], "confirmation": confirmation,
        "invalidation": invalidation, "risks": risks,
        "alternative": opp.title + f" ({opp.probability:.0f}%)", "scenarios": scen, "metrics": res["metrics"],
        "differentials": {"policy_score": _d(sb.policy_score, sq.policy_score),
                          "policy_rate": _d(sb.policy_rate, sq.policy_rate),
                          "inflation": _d(sb.inflation, sq.inflation), "growth": _d(sb.gdp_latest, sq.gdp_latest),
                          "yield_2y": _d(sb.y2, sq.y2), "surprise_index": _d(sb.surprise_index, sq.surprise_index)},
        "report": report, "research_alerts": research_alerts, "disclaimer": SAFETY,
    }


def _d(a, b):
    return None if a is None or b is None else round(a - b, 3)


def _why(conf: tx.Confluence, b: str, q: str) -> list[str]:
    out = []
    for k, v in sorted(conf.factors.items(), key=lambda kv: -abs(kv[1]))[:4]:
        if abs(v) < 1:
            continue
        out.append(f"{tx.LABELS[k]} favours {b if v > 0 else q} ({v:+.0f} of ±{tx.FACTOR_WEIGHTS[k]})")
    return out


def _conclusion(asset: str, bias: str, g: Grade, conf: tx.Confluence, primary: str | None, reasons: list[str]) -> str:
    if g == Grade.NO_TRADE:
        r = reasons[0] if reasons else "insufficient evidence"
        return f"NO TRADE on {asset}. Fundamental lean is {bias.lower()} ({conf.total:+.0f}/100), but {r[0].lower()}{r[1:]}."
    return (f"{asset} has a {bias.lower()} fundamental bias (confluence {conf.total:+.0f}/100, grade {g.value}). "
            f"Primary driver: {primary}. Evidence suggests a potential {conf.direction.lower()} setup, conditional on "
            "the confirmation and invalidation levels below.")


@node("trade_setups", depends_on=("scenarios",), triggers=("full",), label="Trade setups & NO-TRADE engine")
def trade_setups_node(db: Session, ctx: Context) -> None:
    snaps = fnd.build_all(db)
    for asset in se.tracked_assets(db):
        if ctx.currencies and asset[:3] not in ctx.currencies and asset[3:] not in ctx.currencies \
                and ctx.trigger_entity not in ("full", "market_data"):
            continue
        a = analyse(db, asset, snaps)
        prev = db.scalar(select(TradeSetup).where(TradeSetup.asset == asset).order_by(TradeSetup.as_of.desc(),
                                                                                     TradeSetup.id.desc()))
        db.add(TradeSetup(asset=asset, direction=a["direction"], grade=a["grade"], confluence_score=a["confluence_total"],
                          factors=a["factors"], no_trade_reasons=a["no_trade_reasons"], data_status=a["data_status"],
                          grade_cap_reason=a["grade_cap_reason"], primary_driver=a["primary_driver"],
                          secondary_drivers=a["secondary_drivers"], catalysts=a["catalysts"],
                          confirmation=a["confirmation"], invalidation=a["invalidation"], risks=a["risks"],
                          alternative=a["alternative"], research_alerts=a["research_alerts"]))
        db.add(FundamentalAnalysis(asset=asset, bias=a["bias"], conviction=a["conviction"],
                                   evidence_quality=a["evidence_quality"], forecast_confidence=a["forecast_confidence"],
                                   scenario_confidence=a["scenario_confidence"], differentials=a["differentials"],
                                   report=a["report"]))
        prev_bias = db.scalar(select(TradeBias).where(TradeBias.asset == asset).order_by(TradeBias.as_of.desc()))
        if prev_bias is None or prev_bias.bias != a["bias"]:
            db.add(TradeBias(asset=asset, bias=a["bias"], previous_bias=prev_bias.bias if prev_bias else None))
            if prev_bias is not None:
                alert(db, "bias_change", f"{asset} fundamental bias {prev_bias.bias} → {a['bias']}",
                      a["report"]["conclusion"], "MEDIUM", entity="trade_setup")
        if a["grade"] in ("A", "A+") and (prev is None or prev.grade not in ("A", "A+")):
            alert(db, "high_conviction_setup", f"{asset}: grade {a['grade']} {a['direction'].lower()} setup",
                  a["report"]["conclusion"] + " " + SAFETY, "HIGH", entity="trade_setup")
            ctx.change(f"{asset}: new grade {a['grade']} setup.")
        if prev is not None and prev.grade in ("A+", "A", "B") and a["grade"] == "NO TRADE":
            alert(db, "thesis_invalidation", f"{asset}: thesis no longer supported",
                  "Now NO TRADE: " + "; ".join(a["no_trade_reasons"][:2]), "HIGH", entity="trade_setup")
            ctx.change(f"{asset}: setup downgraded to NO TRADE.")


@node("watchlist_alerts", depends_on=("trade_setups",), triggers=("full",), label="Watchlists")
def watchlist_node(db: Session, ctx: Context) -> None:
    for w in db.scalars(select(Watchlist)):
        s = db.scalar(select(TradeSetup).where(TradeSetup.asset == w.asset).order_by(TradeSetup.as_of.desc(),
                                                                                     TradeSetup.id.desc()))
        fa = db.scalar(select(FundamentalAnalysis).where(FundamentalAnalysis.asset == w.asset)
                       .order_by(FundamentalAnalysis.as_of.desc(), FundamentalAnalysis.id.desc()))
        if not s or not fa:
            continue
        if w.alert_on_bias_change and w.last_bias and (w.last_bias != fa.bias or w.last_grade != s.grade):
            alert(db, "watchlist", f"Watchlist {w.asset}: {w.last_bias}/{w.last_grade} → {fa.bias}/{s.grade}",
                  fa.report.get("conclusion", ""), "MEDIUM", entity="watchlist", entity_id=w.id)
        w.last_bias, w.last_grade = fa.bias, s.grade


def latest_setup(db: Session, asset: str) -> TradeSetup | None:
    return db.scalar(select(TradeSetup).where(TradeSetup.asset == asset).order_by(TradeSetup.as_of.desc(),
                                                                                 TradeSetup.id.desc()))


def top_setups(db: Session, n: int = 5) -> list[dict]:
    out = []
    for asset in se.tracked_assets(db):
        s = latest_setup(db, asset)
        if s:
            out.append({"asset": asset, "direction": s.direction, "grade": s.grade, "confluence": s.confluence_score,
                        "primary_driver": s.primary_driver, "data_status": s.data_status,
                        "no_trade_reasons": s.no_trade_reasons, "as_of": s.as_of})
    order = {"A+": 0, "A": 1, "B": 2, "C": 3, "NO TRADE": 4}
    out.sort(key=lambda x: (order.get(x["grade"], 5), -abs(x["confluence"])))
    return out[:n]
