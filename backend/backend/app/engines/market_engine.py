"""Market intelligence engine (Phase 4): yield curves, rate-expectation repricing,
market reaction analysis and market overviews."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import market as mx
from app.db import utcnow
from app.engines import fundamentals as fnd
from app.ingestion.markets import SYMBOLS, price_at
from app.models import (
    BondYield,
    CentralBank,
    EconomicRelease,
    EconomicSurprise,
    Indicator,
    MarketPrice,
    MarketReaction,
    RateExpectation,
    YieldCurve,
)
from app.services.audit import alert
from app.services.recompute import Context, node


def _aware(ts: datetime) -> datetime:
    from datetime import timezone

    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@node("yield_curves", triggers=("market_data", "full"), label="Yield curves")
def yield_curves_node(db: Session, ctx: Context) -> None:
    countries = [c for (c,) in db.execute(select(BondYield.country).distinct())]
    for c in countries:
        pts = {}
        for tenor in ("2Y", "5Y", "10Y", "30Y"):
            y = fnd.latest_yield(db, c, tenor)
            if y:
                pts[tenor] = y.yield_pct
        if not pts:
            continue
        cv = mx.curve(pts)
        prev = db.scalar(select(YieldCurve).where(YieldCurve.country == c).order_by(YieldCurve.as_of.desc()))
        db.add(YieldCurve(country=c, points=pts, slope_2s10s_bps=cv.slope_2s10s_bps, shape=cv.shape))
        if prev and prev.shape and cv.shape and prev.shape != cv.shape:
            alert(db, "yield_curve", f"{c} yield curve now {cv.shape.lower()}",
                  f"2s10s {prev.slope_2s10s_bps} → {cv.slope_2s10s_bps} bps", "MEDIUM", entity="yield_curve")
        if prev and prev.points.get("2Y") is not None and pts.get("2Y") is not None:
            mv = (pts["2Y"] - prev.points["2Y"]) * 100
            if abs(mv) >= 15:
                alert(db, "yield_move", f"{c} 2Y yield {mv:+.0f} bps", f"{prev.points['2Y']:.2f}% → {pts['2Y']:.2f}%",
                      "MEDIUM", entity="yield_curve")
                ctx.change(f"{c} 2Y yield {mv:+.0f} bps.")


def repricing_around(db: Session, cb_code: str, ts: datetime | None) -> dict | None:
    if ts is None:
        return None
    ts = _aware(ts)
    before = db.scalar(select(RateExpectation).where(RateExpectation.central_bank_code == cb_code,
                                                     RateExpectation.ts < ts).order_by(RateExpectation.ts.desc()))
    after = db.scalar(select(RateExpectation).where(RateExpectation.central_bank_code == cb_code,
                                                    RateExpectation.ts >= ts).order_by(RateExpectation.ts))
    if not before or not after:
        return None

    def d(r):
        return {"prob_cut": r.prob_cut, "prob_hold": r.prob_hold, "prob_hike": r.prob_hike,
                "implied_change_bps": r.implied_change_bps, "ts": r.ts}

    res = mx.repricing(d(before), d(after))
    if res:
        res["before"], res["after"] = d(before), d(after)
    return res


@node("rate_repricing", triggers=("rate_expectation", "full"), label="Rate expectation repricing")
def rate_repricing_node(db: Session, ctx: Context) -> None:
    for code in list(ctx.central_banks):
        rows = list(db.scalars(select(RateExpectation).where(RateExpectation.central_bank_code == code)
                               .order_by(RateExpectation.ts.desc()).limit(2)))
        if len(rows) < 2:
            continue
        after, before = rows

        def d(r):
            return {"prob_cut": r.prob_cut, "prob_hold": r.prob_hold, "prob_hike": r.prob_hike}

        res = mx.repricing(d(before), d(after))
        if res and res["label"] != "No material repricing":
            ctx.change(f"{code}: {res['label']} ({res['explanation']})")
            alert(db, "rate_repricing", f"{code}: {res['label']}", res["explanation"],
                  "HIGH" if abs(res["net_hawkish_shift"]) >= 25 else "MEDIUM", entity="rate_expectation",
                  central_bank_code=code)


def yields_around(db: Session, currency: str, ts: datetime | None) -> dict | None:
    if ts is None:
        return None
    ts = _aware(ts)
    c = fnd.YIELD_COUNTRY.get(currency)
    out = {}
    for tenor in ("2Y", "5Y", "10Y", "30Y"):
        b = db.scalar(select(BondYield).where(BondYield.country == c, BondYield.tenor == tenor, BondYield.ts <= ts)
                      .order_by(BondYield.ts.desc()))
        a = db.scalar(select(BondYield).where(BondYield.country == c, BondYield.tenor == tenor, BondYield.ts > ts)
                      .order_by(BondYield.ts))
        if a and b:
            out[f"{c}{tenor}"] = {"before": b.yield_pct, "after": a.yield_pct,
                                  "change_bps": mx.bps_change(b.yield_pct, a.yield_pct), "after_ts": a.ts}
    return out or None


def reaction_symbols(currency: str) -> list[str]:
    syms = [s for s in SYMBOLS if len(s) == 6 and currency in (s[:3], s[3:])]
    if currency == "USD":
        syms += ["XAUUSD", "SPX", "BTCUSD", "WTI"]
    return list(dict.fromkeys(syms))


def compute_reaction(db: Session, entity: str, entity_id: int, ts: datetime, currency: str,
                     direction: str) -> MarketReaction | None:
    ts = _aware(ts)
    syms = reaction_symbols(currency)
    c = fnd.YIELD_COUNTRY.get(currency)
    windows: dict[str, dict] = {}
    any_data = False
    for w, minutes in mx.WINDOWS_MIN.items():
        end = ts + timedelta(minutes=minutes)
        if end > utcnow():
            continue
        moves = {}
        for s in syms:
            p0 = price_at(db, s, ts)
            p1 = price_at(db, s, end)
            if p0 and p1 and p1.ts > p0.ts:
                moves[s] = mx.pct_change(p0.price, p1.price)
                any_data = True
        for tenor in ("2Y", "10Y"):
            b = db.scalar(select(BondYield).where(BondYield.country == c, BondYield.tenor == tenor,
                                                  BondYield.ts <= ts).order_by(BondYield.ts.desc()))
            a = db.scalar(select(BondYield).where(BondYield.country == c, BondYield.tenor == tenor,
                                                  BondYield.ts <= end, BondYield.ts > ts)
                          .order_by(BondYield.ts.desc()))
            if a and b:
                moves[f"{c}{tenor}"] = mx.bps_change(b.yield_pct, a.yield_pct)
                any_data = True
        if moves:
            windows[w] = moves
    if not any_data:
        return None
    expected = mx.expected_reaction(currency, direction, syms + [f"{c}2Y", f"{c}10Y"])
    div = mx.divergences(windows, expected)
    db.execute(delete(MarketReaction).where(MarketReaction.event_entity == entity, MarketReaction.event_id == entity_id))
    mr = MarketReaction(event_entity=entity, event_id=entity_id, event_time=ts, windows=windows,
                        expected={k: v for k, v in expected.items() if v}, divergences=div)
    if div:
        regime = fnd.latest_regime(db)
        mr.divergences = div + [{"explanation": mx.explain_divergence(div, None, regime.secondary if regime
                                                                       else None)}]
    db.add(mr)
    return mr


@node("market_reaction", depends_on=("surprise", "cb_surprise"), label="Market reaction")
def market_reaction_node(db: Session, ctx: Context) -> None:
    for rid in ctx.release_ids:
        rel = db.get(EconomicRelease, rid)
        if rel is None or rel.released_at is None:
            continue
        ind = db.get(Indicator, rel.indicator_id)
        s = db.scalar(select(EconomicSurprise).where(EconomicSurprise.release_id == rel.id))
        mr = compute_reaction(db, "release", rel.id, rel.released_at, ind.currency,
                              s.policy_direction if s else "Neutral")
        if mr and mr.divergences and ind.importance == "high":
            d0 = mr.divergences[0]
            alert(db, "reaction_divergence", f"{ind.name}: market reaction diverged from expectations",
                  d0.get("note", ""), "MEDIUM", entity="economic_release", entity_id=rel.id, currency=ind.currency)


def latest_reaction_for_cb(db: Session, cb: CentralBank) -> dict | None:
    mr = db.scalar(select(MarketReaction).where(MarketReaction.event_entity.in_(["statement", "meeting"]))
                   .order_by(MarketReaction.event_time.desc()))
    if mr is None:
        return None
    return {"event": mr.event_entity, "event_time": mr.event_time, "windows": mr.windows, "expected": mr.expected,
            "divergences": mr.divergences}


def markets_overview(db: Session) -> list[dict]:
    out = []
    for sym, (_, cls) in SYMBOLS.items():
        last = db.scalar(select(MarketPrice).where(MarketPrice.symbol == sym).order_by(MarketPrice.ts.desc()))
        if last is None:
            out.append({"symbol": sym, "asset_class": cls, "price": None})
            continue
        day = price_at(db, sym, last.ts - timedelta(days=1))
        week = price_at(db, sym, last.ts - timedelta(days=7))
        month = price_at(db, sym, last.ts - timedelta(days=30))
        out.append({"symbol": sym, "asset_class": cls, "price": last.price, "ts": last.ts, "source": last.source,
                    "input_method": last.input_method, "verification_status": last.verification_status,
                    "change_1d_pct": mx.pct_change(day.price, last.price) if day else None,
                    "change_1w_pct": mx.pct_change(week.price, last.price) if week else None,
                    "change_1m_pct": mx.pct_change(month.price, last.price) if month else None})
    return out


def yields_overview(db: Session) -> list[dict]:
    out = []
    for (c,) in db.execute(select(BondYield.country).distinct()):
        row = {"country": c}
        for t in ("2Y", "5Y", "10Y", "30Y"):
            y = fnd.latest_yield(db, c, t)
            if y:
                old = fnd.latest_yield(db, c, t, before=y.ts - timedelta(days=7))
                row[t] = {"yield": y.yield_pct, "ts": y.ts,
                          "change_1w_bps": mx.bps_change(old.yield_pct, y.yield_pct) if old else None}
        cv = db.scalar(select(YieldCurve).where(YieldCurve.country == c).order_by(YieldCurve.as_of.desc()))
        if cv:
            row["slope_2s10s_bps"], row["shape"] = cv.slope_2s10s_bps, cv.shape
        out.append(row)
    return out


def rates_overview(db: Session) -> list[dict]:
    out = []
    for cb in db.scalars(select(CentralBank)):
        snap = fnd.build(db, cb.currency)
        rx = fnd.latest_rate_expectation(db, cb.code)
        out.append({"central_bank": cb.code, "currency": cb.currency, "policy_rate": snap.policy_rate,
                    "prob_cut": rx.prob_cut if rx else None, "prob_hold": rx.prob_hold if rx else None,
                    "prob_hike": rx.prob_hike if rx else None,
                    "implied_12m_change_bps": snap.implied_change_bps, "implied_is_proxy": snap.implied_is_proxy,
                    "as_of": rx.ts if rx else None})
    return out


def price_move(db: Session, asset: str, days: int = 28) -> float | None:
    last = db.scalar(select(MarketPrice).where(MarketPrice.symbol == asset).order_by(MarketPrice.ts.desc()))
    if last is None:
        return None
    old = price_at(db, asset, last.ts - timedelta(days=days))
    return mx.pct_change(old.price, last.price) if old else None

