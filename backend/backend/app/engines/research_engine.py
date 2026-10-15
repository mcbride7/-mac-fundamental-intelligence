"""Advanced research (Phase 7): "Is the market wrong?", historical analogues,
conditional event studies and central-bank forecast rankings."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import research as rs
from app.analytics.forecast import policy_implication
from app.engines import fundamentals as fnd
from app.models import (
    CentralBank,
    EconomicRelease,
    ForecastAccuracy,
    ForecastError,
    MacroRegime,
    MarketPrice,
    PolicyScore,
)
from app.services import data_access as da
from app.services.audit import alert
from app.services.recompute import Context, node


def market_wrong_checks(db: Session, codes: set[str] | None = None) -> list[dict]:
    out = []
    for cb in db.scalars(select(CentralBank)):
        if codes and cb.code not in codes:
            continue
        snap = fnd.build(db, cb.currency)
        imp = policy_implication(snap.deviations)["score"] if snap.deviations else None
        dev = snap.deviations
        r = rs.market_wrong(cb.code, imp, snap.policy_score, snap.prob_cut, snap.prob_hike,
                            None if snap.implied_is_proxy else snap.implied_change_bps,
                            dev.get("core_inflation", dev.get("inflation")))
        if r:
            r["evidence"] = {"policy_score": snap.policy_score, "deviations": dev, "prob_cut": snap.prob_cut,
                             "prob_hike": snap.prob_hike, "implied_12m_change_bps": snap.implied_change_bps}
            out.append(r)
    return out


@node("market_wrong", depends_on=("policy_score", "rate_repricing"), triggers=("full",),
      label="Is the market wrong?")
def market_wrong_node(db: Session, ctx: Context) -> None:
    for r in market_wrong_checks(db, ctx.central_banks or None):
        alert(db, "market_wrong", r["title"], r["body"], "MEDIUM", entity="central_bank",
              central_bank_code=r["central_bank"], **{"gap": r["gap"]})
        ctx.change(r["title"] + ".")


def _prices(db: Session, symbol: str) -> list[tuple[datetime, float]]:
    return [(fnd._aware(p.ts), p.price) for p in db.scalars(select(MarketPrice).where(MarketPrice.symbol == symbol)
                                                            .order_by(MarketPrice.ts))]


def usd_proxy_symbol(db: Session) -> tuple[str, int]:
    """DXY if available, else EURUSD inverted."""
    if db.scalar(select(MarketPrice.symbol).where(MarketPrice.symbol == "DXY")):
        return "DXY", 1
    return "EURUSD", -1


def event_study(db: Session, cb_code: str, variable: str, condition: str = "above", asset: str | None = None,
                horizons: tuple[int, ...] = (1, 5, 20)) -> dict:
    """e.g. 'When inflation exceeded Fed projections, how did USD perform?'"""
    cb = da.cb_by_code(db, cb_code)
    if cb is None:
        raise LookupError("Unknown central bank")
    rows = db.execute(select(ForecastError, EconomicRelease)
                      .join(EconomicRelease, ForecastError.release_id == EconomicRelease.id)
                      .where(ForecastError.central_bank_id == cb.id, ForecastError.variable == variable,
                             ForecastError.basis == "real_time", ForecastError.cb_error.is_not(None))).all()
    times = [fnd._aware(rel.released_at) for fe, rel in rows if rel.released_at and
             ((fe.cb_error > 0.1) if condition == "above" else (fe.cb_error < -0.1))]
    if asset:
        sym, sign = asset.upper(), 1
    elif cb.currency == "USD":
        sym, sign = usd_proxy_symbol(db)
    else:
        from app.ingestion.markets import currency_pair_for

        sym, sign = currency_pair_for(cb.currency) or ("EURUSD", 1)
    res = rs.conditional_returns(times, _prices(db, sym), horizons)
    if sign == -1:
        for h in res.get("horizons", {}).values():
            h["mean_pct"], h["median_pct"] = -h["mean_pct"], -h["median_pct"]
            h["hit_rate_up"] = round(1 - h["hit_rate_up"], 2)
    return {"question": f"When {variable.replace('_', ' ')} came in {condition} {cb.short_name} projections, "
                        f"how did {cb.currency} perform?",
            "events": len(times), "measured_with": f"{sym}{' (inverted)' if sign == -1 else ''}", **res}


def state_history(db: Session, base: str, quote: str) -> list[rs.StatePoint]:
    cbb, cbq = da.cb_by_currency(db, base), da.cb_by_currency(db, quote)
    if not cbb or not cbq:
        return []
    by_month: dict[str, dict] = defaultdict(dict)
    for cb, key in ((cbb, "base_policy"), (cbq, "quote_policy")):
        for p in db.scalars(select(PolicyScore).where(PolicyScore.central_bank_id == cb.id)):
            by_month[p.as_of.strftime("%Y-%m")][key] = p.score
    for ccy, key in ((base, "base_infl"), (quote, "quote_infl")):
        code = fnd.HEADLINE_INFL.get(fnd.COUNTRY[ccy])
        ind = da.indicator_by_code(db, code) if code else None
        if ind:
            for r in da.current_series(db, ind.id, 240):
                by_month[r.reference_period[:7]][key] = r.actual
    pts = []
    for m, v in sorted(by_month.items()):
        vec = {}
        if "base_policy" in v and "quote_policy" in v:
            vec["policy_divergence"] = v["base_policy"] - v["quote_policy"]
        if "base_infl" in v and "quote_infl" in v:
            vec["inflation_differential"] = v["base_infl"] - v["quote_infl"]
        if vec:
            try:
                pts.append(rs.StatePoint(datetime.strptime(m, "%Y-%m").replace(tzinfo=fnd.utcnow().tzinfo), vec))
            except ValueError:
                continue
    return pts


def historical_analogues(db: Session, asset: str, k: int = 5) -> dict:
    asset = asset.upper()
    b, q = asset[:3], asset[3:]
    sb, sq = fnd.build(db, b), fnd.build(db, q)
    current = {"policy_divergence": _d(sb.policy_score, sq.policy_score),
               "inflation_differential": _d(sb.inflation, sq.inflation)}
    hist = state_history(db, b, q)
    now = fnd.utcnow()
    hist = [h for h in hist if (now - h.when).days > 45]
    matches = rs.analogues(current, hist, k)
    prices = _prices(db, asset)
    for m in matches:
        r = rs.conditional_returns([m["when"]], prices, (20, 60))
        m["subsequent"] = r.get("horizons", {})
        regime = db.scalar(select(MacroRegime).where(MacroRegime.as_of <= m["when"] + timedelta(days=31))
                           .order_by(MacroRegime.as_of.desc()))
        m["regime"] = regime.primary if regime else None
    return {"asset": asset, "current_state": current, "analogues": matches, "disclaimer": rs.DISCLAIMER,
            "note": None if matches else "Not enough stored history yet. History accumulates as the platform runs; "
                                         "backfill projections, releases and prices to enable analogue matching."}


def _d(a, b):
    return None if a is None or b is None else a - b


def forecast_rankings(db: Session, variable: str | None = None, basis: str = "real_time",
                      window: str = "5y") -> dict:
    q = select(ForecastAccuracy).where(ForecastAccuracy.basis == basis, ForecastAccuracy.window == window,
                                       ~ForecastAccuracy.forecaster.contains(":"))
    if variable:
        q = q.where(ForecastAccuracy.variable == variable)
    rows = [{"forecaster": r.forecaster, "variable": r.variable, "score": r.score, "n": r.n, "mae": r.mae}
            for r in db.scalars(q)]
    per_var = defaultdict(list)
    for r in rows:
        per_var[r["variable"]].append(r)
    for v in per_var.values():
        v.sort(key=lambda x: -x["score"])
    return {"basis": basis, "window": window, "overall": rs.rank_forecasters(rows), "by_variable": per_var}

