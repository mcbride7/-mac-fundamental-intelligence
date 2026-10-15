"""Forecast intelligence engine (Phase 3): projection vs actual, three-way comparison,
accuracy, bias, revisions, "where are we now?" and miss explanations."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.llm import DATA_GUARD, get_llm
from app.analytics import forecast as fx
from app.db import utcnow
from app.models import (
    CentralBank,
    CentralBankProjection,
    EconomicEvent,
    EconomicForecast,
    EconomicRelease,
    ForecastAccuracy,
    ForecastBias,
    ForecastError,
    ForecastRevision,
    Indicator,
    MarketPrice,
    ProjectionVintage,
)
from app.services import data_access as da
from app.services.audit import alert
from app.services.recompute import Context, node

ACCURACY_WINDOWS = ["last4", "last8", "last12", "2y", "5y"]


def _scope(db: Session, ctx: Context) -> list[EconomicRelease]:
    rels: dict[int, EconomicRelease] = {}
    for rid in ctx.release_ids:
        r = db.get(EconomicRelease, rid)
        if r is not None:
            rels[r.id] = r
    for iid in ctx.indicator_ids:
        r = da.latest_current(db, iid)
        if r is not None:
            rels[r.id] = r
    if ctx.trigger_entity in ("projection_vintage", "full"):
        cbs = ctx.central_banks or {c.code for c in db.scalars(select(CentralBank))}
        for code in cbs:
            for ind in db.scalars(select(Indicator).where(Indicator.central_bank_code == code,
                                                          Indicator.projection_variable.is_not(None))):
                for r in da.current_series(db, ind.id, 120):
                    rels[r.id] = r
    return list(rels.values())


def explain_miss(db: Session, ind: Indicator, rel: EconomicRelease, cb_error: float, vintage_date) -> dict:
    """Evidence-only explanation of a material forecast miss (Section 24). Uses only data
    stored in the platform — never invents a cause."""
    evidence = []
    start = vintage_date
    end = rel.released_at or utcnow()

    def move(symbol: str, label: str):
        p0 = db.scalar(select(MarketPrice).where(MarketPrice.symbol == symbol, MarketPrice.ts >= start)
                       .order_by(MarketPrice.ts))
        p1 = db.scalar(select(MarketPrice).where(MarketPrice.symbol == symbol, MarketPrice.ts <= end)
                       .order_by(MarketPrice.ts.desc()))
        if p0 and p1 and p0.price:
            ch = (p1.price / p0.price - 1) * 100
            evidence.append({"factor": label, "observation": f"{symbol} {ch:+.1f}% between projection and release",
                             "value": round(ch, 2), "source": p1.source or "market data"})

    if ind.category == "inflation":
        move("WTI", "Energy prices")
        move("XAUUSD", "Commodity prices")
        ccy_pair = {"EUR": "EURUSD", "GBP": "GBPUSD", "JPY": "USDJPY", "ZAR": "USDZAR", "MXN": "USDMXN",
                    "CAD": "USDCAD", "AUD": "AUDUSD", "NZD": "NZDUSD", "CHF": "USDCHF"}.get(ind.currency)
        if ccy_pair:
            move(ccy_pair, "Currency movements")
        wage = da.indicator_by_code(db, f"{ind.country}_AHE_YOY")
        if wage:
            w = da.latest_current(db, wage.id)
            if w:
                evidence.append({"factor": "Wage growth", "observation": f"{wage.name} {w.actual:g}% "
                                                                          f"({w.reference_period})",
                                 "value": w.actual, "source": w.source_name})
    if ind.category in ("growth", "employment"):
        for code in (f"{ind.country}_RETAIL_SALES_MOM", f"{ind.country}_ISM_MANUF", f"{ind.country}_PMI_COMPOSITE"):
            i2 = da.indicator_by_code(db, code)
            if i2:
                r2 = da.latest_current(db, i2.id)
                if r2:
                    evidence.append({"factor": "Demand / business activity",
                                     "observation": f"{i2.name} {r2.actual:g} ({r2.reference_period})",
                                     "value": r2.actual, "source": r2.source_name})
    direction = "above" if cb_error > 0 else "below"
    out = {"summary": f"Actual was {abs(cb_error):.2f} pp {direction} the projection.", "evidence": evidence,
           "method": "evidence_only"}
    if not evidence:
        out["summary"] += (" There is not enough evidence stored in the platform to explain the miss. "
                           "Add market data or source documents (e.g. the statistical release) to investigate.")
        return out
    llm = get_llm()
    if llm.available:
        try:
            prompt = ("Using ONLY the evidence list below, write 2-3 sentences on what plausibly contributed to the "
                      f"forecast miss of {ind.name} ({cb_error:+.2f} pp). If the evidence is insufficient, say so. "
                      f"Do not add facts.\nEvidence: {evidence}")
            out["narrative"] = llm.complete(DATA_GUARD, prompt, 300).text.strip()
            out["method"] = "evidence_plus_llm"
        except Exception:
            pass
    return out


def compute_errors(db: Session, rel: EconomicRelease) -> list[ForecastError]:
    ind = db.get(Indicator, rel.indicator_id)
    db.execute(delete(ForecastError).where(ForecastError.release_id == rel.id))
    ev = db.get(EconomicEvent, rel.event_id) if rel.event_id else None
    market = rel.consensus if rel.consensus is not None else (ev.consensus if ev else None)
    economist = None
    if ev is not None:
        e = db.scalar(select(EconomicForecast).where(EconomicForecast.event_id == ev.id,
                                                     EconomicForecast.forecaster == "economist")
                      .order_by(EconomicForecast.as_of.desc()))
        economist = e.value if e else None
    cb = da.cb_by_code(db, ind.central_bank_code) if ind.central_bank_code else None
    first = da.first_release(db, ind.id, rel.reference_period) or rel
    out = []
    as_of = first.released_at or rel.released_at
    pr = None
    if cb and ind.projection_variable:
        pr = da.projection_for(db, cb.id, ind.projection_variable, rel.reference_period[:4], as_of)
    for basis, actual in (("real_time", first.actual), ("final", rel.actual)):
        if basis == "final" and first.id == rel.id:
            continue
        tw = fx.three_way(actual, pr[0].value if pr else None, market, economist, ind.projection_variable)
        if tw.cb_error is None and tw.market_error is None:
            continue
        fe = ForecastError(release_id=rel.id, indicator_id=ind.id, central_bank_id=cb.id if cb else None,
                           projection_id=pr[0].id if pr else None, variable=ind.projection_variable,
                           actual=actual, cb_projection=tw.cb, market_forecast=tw.market,
                           economist_forecast=tw.economist, cb_error=tw.cb_error, market_error=tw.market_error,
                           economist_error=tw.economist_error, cb_classification=tw.cb_classification,
                           more_accurate=tw.more_accurate, basis=basis)
        if basis == "real_time" and tw.cb_classification and tw.cb_classification.startswith("Significantly"):
            fe.miss_explanation = explain_miss(db, ind, rel, tw.cb_error, pr[1].vintage_date)
        db.add(fe)
        out.append(fe)
    return out


@node("forecast_error", triggers=("release", "projection_vintage", "full"), label="Projection vs actual")
def forecast_error_node(db: Session, ctx: Context) -> None:
    for rel in _scope(db, ctx):
        ind = db.get(Indicator, rel.indicator_id)
        if not rel.is_current:
            continue
        for fe in compute_errors(db, rel):
            if fe.basis != "real_time" or fe.cb_error is None:
                continue
            cb = db.get(CentralBank, fe.central_bank_id)
            if cb:
                ctx.central_banks.add(cb.code)
            ctx.currencies.add(ind.currency)
            if rel.id in ctx.release_ids and fe.cb_classification and fe.cb_classification != "In Line":
                implication = fx.HIGHER_IS.get(fe.variable or "", "Neutral")
                if fe.cb_error < 0:
                    implication = "Dovish" if implication == "Hawkish" else "Hawkish"
                ctx.change(f"{ind.name} {fe.cb_error:+.2f} pp vs {cb.short_name} projection "
                           f"({fe.cb_classification}).")
                alert(db, "forecast_miss", f"{cb.short_name}: {ind.name} {fe.cb_classification.lower()}",
                      f"{ind.name} is {abs(fe.cb_error):.1f} percentage points "
                      f"{'above' if fe.cb_error > 0 else 'below'} {cb.short_name}'s projection "
                      f"({fe.cb_projection:g}% → {fe.actual:g}%). Forecast status: MISS. "
                      f"Policy implication: MORE {implication.upper()}.",
                      "HIGH" if fe.cb_classification.startswith("Significantly") else "MEDIUM",
                      entity="economic_release", entity_id=rel.id, currency=ind.currency,
                      central_bank_code=cb.code)


def _errors_by_forecaster(db: Session, basis: str) -> dict[tuple[str, str], list[tuple[str, float]]]:
    out: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    rows = db.execute(select(ForecastError, EconomicRelease, CentralBank)
                      .join(EconomicRelease, ForecastError.release_id == EconomicRelease.id)
                      .outerjoin(CentralBank, ForecastError.central_bank_id == CentralBank.id)
                      .where(ForecastError.basis == basis)).all()
    seen: set[tuple] = set()
    for fe, rel, cb in rows:
        key = (fe.indicator_id, rel.reference_period)
        if key in seen:
            continue
        seen.add(key)
        if fe.variable is None:
            continue
        if fe.cb_error is not None and cb is not None:
            out[(cb.code, fe.variable)].append((rel.reference_period, fe.cb_error))
        if fe.market_error is not None:
            out[(f"market:{cb.code if cb else 'na'}", fe.variable)].append((rel.reference_period, fe.market_error))
        if fe.economist_error is not None:
            out[(f"economist:{cb.code if cb else 'na'}", fe.variable)].append(
                (rel.reference_period, fe.economist_error))
    for k in out:
        out[k].sort()
    return out


@node("forecast_accuracy", depends_on=("forecast_error",), label="Forecast accuracy")
def forecast_accuracy_node(db: Session, ctx: Context) -> None:
    year = utcnow().year
    db.execute(delete(ForecastAccuracy))
    for basis in ("real_time", "final"):
        for (forecaster, var), errs in _errors_by_forecaster(db, basis).items():
            for w in ACCURACY_WINDOWS:
                e = fx.windowed(errs, w, year)
                a = fx.accuracy(e, var)
                if a:
                    db.add(ForecastAccuracy(forecaster=forecaster, variable=var, window=w, basis=basis, n=a.n,
                                            mae=a.mae, rmse=a.rmse, mean_error=a.mean_error, score=a.score))


@node("forecast_bias", depends_on=("forecast_accuracy",), label="Forecast bias")
def forecast_bias_node(db: Session, ctx: Context) -> None:
    db.execute(delete(ForecastBias))
    for (forecaster, var), errs in _errors_by_forecaster(db, "real_time").items():
        b = fx.bias([e for _, e in errs[-12:]], var)
        db.add(ForecastBias(forecaster=forecaster, variable=var, classification=b.classification,
                            mean_error=b.mean_error, hit_rate_same_sign=b.same_sign_share, n=b.n, t_stat=b.t_stat,
                            explanation=b.explanation))


@node("forecast_revisions", triggers=("projection_vintage", "full"), label="Forecast revisions")
def forecast_revisions_node(db: Session, ctx: Context) -> None:
    cbs = ctx.central_banks or {c.code for c in db.scalars(select(CentralBank))}
    for code in cbs:
        cb = da.cb_by_code(db, code)
        if cb is None:
            continue
        rows = db.execute(select(CentralBankProjection, ProjectionVintage)
                          .join(ProjectionVintage, CentralBankProjection.vintage_id == ProjectionVintage.id)
                          .where(CentralBankProjection.central_bank_id == cb.id)
                          .order_by(ProjectionVintage.vintage_date)).all()
        paths: dict[tuple[str, str], list] = defaultdict(list)
        for p, v in rows:
            paths[(p.variable, p.target_period)].append({"vintage": v.vintage_date.isoformat(), "label": v.label,
                                                          "value": p.value})
        db.execute(delete(ForecastRevision).where(ForecastRevision.central_bank_id == cb.id))
        for (var, period), path in paths.items():
            r = fx.revision_momentum([x["value"] for x in path], var)
            db.add(ForecastRevision(central_bank_id=cb.id, variable=var, target_period=period, path=path,
                                    momentum=r.momentum, total_change=r.total_change, interpretation=r.interpretation))
            if len(path) >= 2 and ctx.trigger_entity == "projection_vintage":
                last = path[-1]["value"] - path[-2]["value"]
                if abs(last) >= fx.THRESHOLDS.get(var, 0.2):
                    alert(db, "forecast_revision", f"{cb.short_name} revised {var.replace('_', ' ')} {period} "
                                                   f"{'up' if last > 0 else 'down'}",
                          f"{path[-2]['value']:g} → {path[-1]['value']:g} ({last:+.2f} pp). {r.interpretation}",
                          "MEDIUM", entity="central_bank", entity_id=cb.id, currency=cb.currency,
                          central_bank_code=cb.code)
                    ctx.change(f"{cb.short_name} {var.replace('_', ' ')} {period} projection revised "
                               f"{path[-2]['value']:g} → {path[-1]['value']:g}.")
        ctx.currencies.add(cb.currency)


# ---------------------------------------------------------------------------
# read models for the API
# ---------------------------------------------------------------------------

def accuracy_summary(db: Session, cb_code: str, variable: str | None = None, basis: str = "real_time",
                     window: str = "last8") -> dict:
    q = select(ForecastAccuracy).where(ForecastAccuracy.basis == basis, ForecastAccuracy.window == window,
                                       ForecastAccuracy.forecaster.in_([cb_code, f"market:{cb_code}",
                                                                        f"economist:{cb_code}"]))
    if variable:
        q = q.where(ForecastAccuracy.variable == variable)
    rows = list(db.scalars(q))
    out: dict = {"basis": basis, "window": window, "central_bank": {}, "market": {}, "economist": {}}
    for r in rows:
        who = "central_bank" if r.forecaster == cb_code else r.forecaster.split(":")[0]
        out[who][r.variable] = {"score": r.score, "mae": r.mae, "rmse": r.rmse, "mean_error": r.mean_error, "n": r.n}
    cb_scores = [v["score"] for v in out["central_bank"].values()]
    out["overall"] = round(sum(cb_scores) / len(cb_scores), 1) if cb_scores else None
    best = {}
    for var in set(out["central_bank"]) | set(out["market"]) | set(out["economist"]):
        cands = {k: out[k][var]["mae"] for k in ("central_bank", "market", "economist") if var in out[k]}
        if cands:
            best[var] = min(cands, key=cands.get)
    out["most_accurate"] = best
    biases = list(db.scalars(select(ForecastBias).where(ForecastBias.forecaster == cb_code)))
    out["bias"] = {b.variable: {"classification": b.classification, "mean_error": b.mean_error, "n": b.n,
                                "explanation": b.explanation} for b in biases}
    return out


def where_are_we(db: Session, cb_code: str) -> dict:
    cb = da.cb_by_code(db, cb_code)
    if cb is None:
        raise LookupError("Unknown central bank")
    table, deviations = [], {}
    for ind in db.scalars(select(Indicator).where(Indicator.central_bank_code == cb.code,
                                                  Indicator.projection_variable.is_not(None))):
        if ind.projection_variable == "policy_rate":
            continue
        rel = da.latest_current(db, ind.id)
        if rel is None:
            continue
        pr = da.projection_for(db, cb.id, ind.projection_variable, rel.reference_period[:4])
        if pr is None:
            continue
        diff = round(rel.actual - pr[0].value, 3)
        deviations[ind.projection_variable] = diff
        cls = fx.classify_vs_projection(diff, ind.projection_variable)
        table.append({"indicator": ind.name, "variable": ind.projection_variable, "projection": pr[0].value,
                      "projection_vintage": pr[1].label, "current": rel.actual, "period": rel.reference_period,
                      "difference": diff, "classification": cls,
                      "interpretation": _interp(ind.projection_variable, diff, cls),
                      "data_status": rel.verification_status})
    return {"central_bank": cb.code, "table": table, "policy_implication": fx.policy_implication(deviations)}


def _interp(var: str, diff: float, cls: str) -> str:
    if cls == "In Line":
        return "In line with projection"
    if var == "unemployment":
        return "Labour market weaker than projected" if diff > 0 else "Labour market stronger than projected"
    if var == "gdp":
        return "Growth above projection" if diff > 0 else "Growth below projection"
    return "Inflation above projection" if diff > 0 else "Inflation below projection"


def forecastability_table(db: Session) -> list[dict]:
    out = []
    for ind in db.scalars(select(Indicator)):
        errs = [fe.market_error for fe in db.scalars(select(ForecastError).where(
            ForecastError.indicator_id == ind.id, ForecastError.basis == "real_time"))]
        series = [r.actual for r in da.current_series(db, ind.id, 60)]
        changes = [b - a for a, b in zip(series[:-1], series[1:])]
        s = fx.forecastability(errs, changes)
        if s is not None:
            out.append({"indicator": ind.code, "name": ind.name, "forecastability": s, "n": len(errs),
                        "explanation": "Lower forecastability means the indicator has historically produced larger "
                                       "forecasting errors or is more sensitive to unpredictable shocks."})
    return sorted(out, key=lambda x: -x["forecastability"])

