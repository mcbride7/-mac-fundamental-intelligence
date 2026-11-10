"""Track record of the app's trade grades.

Each time an asset gets a new graded call (a different grade or direction from its last one),
the call is frozen with the price at that moment. 1, 5 and 20 days later the price is checked
again and the move in the call's direction is stored. The summary shows, per grade, how often the
call was right and the average move, so the grades can be judged on evidence rather than trust.

Each call also gets a trade plan: swing or day trade, a stop loss and a take profit sized from the pair's
typical daily move (ATR proxy), and a check of which level was reached first."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import MarketPrice
from app.models.track import SignalPlan, SignalRecord

HORIZONS = {"ret_1d": 1, "ret_5d": 5, "ret_20d": 20}
GRADED = ("A+", "A", "B", "C")
MAX_PRICE_GAP = timedelta(days=4)  # weekends and holidays


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _direct(db: Session, symbol: str, ts: datetime) -> MarketPrice | None:
    p = db.scalar(select(MarketPrice).where(MarketPrice.symbol == symbol, MarketPrice.ts <= ts)
                  .order_by(MarketPrice.ts.desc()))
    if p is not None and ts - _aware(p.ts) <= MAX_PRICE_GAP:
        return p
    return None


def _usd_rate(db: Session, ccy: str, ts: datetime) -> tuple[float, datetime] | None:
    """Value of 1 unit of `ccy` in USD, from EURUSD-style or USDJPY-style quotes."""
    if ccy == "USD":
        return 1.0, ts
    p = _direct(db, f"{ccy}USD", ts)
    if p is not None:
        return p.price, p.ts
    p = _direct(db, f"USD{ccy}", ts)
    if p is not None and p.price:
        return 1 / p.price, p.ts
    return None


def _price_near(db: Session, asset: str, ts: datetime) -> SimpleNamespace | None:
    """Price of `asset` at or just before `ts`; crosses like EURGBP are built from their USD legs."""
    p = _direct(db, asset, ts)
    if p is not None:
        return SimpleNamespace(price=p.price, ts=p.ts)
    if len(asset) != 6:
        return None
    b, q = _usd_rate(db, asset[:3], ts), _usd_rate(db, asset[3:], ts)
    if b is None or q is None or not q[0]:
        return None
    return SimpleNamespace(price=round(b[0] / q[0], 6), ts=min(b[1], q[1], key=_aware))


def latest_open(db: Session, asset: str) -> SignalRecord | None:
    return db.scalar(select(SignalRecord).where(SignalRecord.asset == asset, SignalRecord.superseded_at.is_(None))
                     .order_by(SignalRecord.opened_at.desc(), SignalRecord.id.desc()))


def record(db: Session, asset: str, grade: str, direction: str, confluence: float,
           now: datetime | None = None) -> SignalRecord | None:
    """Store a new call if it differs from the asset's current one. NO TRADE closes the current one."""
    now = now or utcnow()
    cur = latest_open(db, asset)
    graded = grade in GRADED and direction in ("LONG", "SHORT")
    if cur is not None and graded and cur.grade == grade and cur.direction == direction:
        return None  # same call as before
    if cur is not None:
        cur.superseded_at = now
    if not graded:
        return None
    p = _price_near(db, asset, now)
    rec = SignalRecord(asset=asset, direction=direction, grade=grade, confluence=confluence, opened_at=now,
                       entry_price=p.price if p else None, entry_price_at=p.ts if p else None,
                       note=None if p else "No price available when the call was made")
    db.add(rec)
    db.flush()
    plan_for(db, rec)
    return rec


def evaluate(db: Session, now: datetime | None = None) -> int:
    """Fill in 1/5/20-day outcomes that have come due. Returns how many were filled."""
    now = now or utcnow()
    n = 0
    q = select(SignalRecord).where(SignalRecord.entry_price.is_not(None),
                                   SignalRecord.ret_20d.is_(None))
    for rec in db.scalars(q):
        for field, days in HORIZONS.items():
            if getattr(rec, field) is not None:
                continue
            due = _aware(rec.opened_at) + timedelta(days=days)
            if due > now:
                continue
            p = _price_near(db, rec.asset, due)
            if p is None or not rec.entry_price:
                continue
            move = (p.price / rec.entry_price - 1) * 100
            setattr(rec, field, round(move if rec.direction == "LONG" else -move, 4))
            n += 1
    db.commit()
    return n


# --------------------------------------------------------------------------- trade plan: SL / TP / swing or day

ATR_DAYS = 14
PLAN = {  # stop and target in multiples of the typical daily move; both give 1 : 2 risk-reward
    "swing": {"sl": 1.5, "tp": 3.0, "days": 20, "label": "Swing trade (held days to weeks)"},
    "day": {"sl": 0.5, "tp": 1.0, "days": 1, "label": "Day trade (closed the same day)"},
}


def _daily_closes(db: Session, asset: str, start: datetime | None = None, end: datetime | None = None) -> list[tuple[datetime, float]]:
    """Daily closes (last price of each day) from stored prices; falls back to the daily FRED / Twelve Data history."""
    q = select(MarketPrice.ts, MarketPrice.price).where(MarketPrice.symbol == asset)
    if start is not None:
        q = q.where(MarketPrice.ts > start)
    if end is not None:
        q = q.where(MarketPrice.ts <= end)
    by_day: dict = {}
    for ts, px in db.execute(q.order_by(MarketPrice.ts)):
        by_day[_aware(ts).date()] = (_aware(ts), px)
    out = list(by_day.values())
    if len(out) >= 8 or start is not None:
        return out
    series = _series(db, asset)
    return [(datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc), v) for d, v in sorted(series.items())
            if end is None or datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) <= end]


def _prices_between(db: Session, asset: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
    """Every stored price after the call (hourly where available), else daily closes."""
    pts = [(_aware(ts), px) for ts, px in db.execute(
        select(MarketPrice.ts, MarketPrice.price).where(MarketPrice.symbol == asset, MarketPrice.ts > start,
                                                        MarketPrice.ts <= end).order_by(MarketPrice.ts))]
    if pts or len(asset) != 6:
        return pts
    out = []
    for d, v in sorted(_series(db, asset).items()):
        ts = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=21)
        if start < ts <= end:
            out.append((ts, v))
    return out


def _series(db: Session, asset: str) -> dict:
    from app.services import intermarket as im

    return im.Loader(db).get(asset)


def typical_move_pct(db: Session, asset: str, at: datetime) -> float | None:
    """Average absolute daily % move over the last 14 days, x1.2 (close-to-close understates the true daily range)."""
    closes = [p for _, p in _daily_closes(db, asset, end=at) if p][-(ATR_DAYS + 1):]
    if len(closes) < 8:
        return None
    moves = [abs(b / a - 1) * 100 for a, b in zip(closes, closes[1:])]
    return round(1.2 * sum(moves) / len(moves), 3)


def _event_soon(db: Session, asset: str, at: datetime) -> str | None:
    from app.models import EconomicEvent, Indicator

    ccys = [asset[:3], asset[3:]] if len(asset) == 6 else ["USD"]
    hit = db.execute(select(EconomicEvent, Indicator).join(Indicator, EconomicEvent.indicator_id == Indicator.id)
                     .where(Indicator.currency.in_(ccys), Indicator.importance == "high",
                            EconomicEvent.scheduled_at >= at, EconomicEvent.scheduled_at <= at + timedelta(hours=24))
                     .order_by(EconomicEvent.scheduled_at)).first()
    return None if hit is None else f"{hit[1].name} due within 24 hours"


def classify(db: Session, rec: SignalRecord) -> tuple[str, str]:
    """Swing for the fundamental calls (they play out over 1-4 weeks); day trade when the call is weak (grade C)
    or a high-impact release is due within 24 hours (an event-driven move)."""
    ev = _event_soon(db, rec.asset, _aware(rec.opened_at))
    if rec.grade == "C":
        return "day", "Grade C: not enough conviction to hold overnight" + (f"; {ev}" if ev else "")
    if ev and rec.grade == "B":
        return "day", f"{ev}: trade the reaction, don't hold through it"
    return "swing", f"Grade {rec.grade} fundamental call: these play out over 1–4 weeks"


def levels(entry: float, direction: str, trade_type: str, atr_pct: float) -> tuple[float, float]:
    cfg = PLAN[trade_type]
    sl_d, tp_d = entry * cfg["sl"] * atr_pct / 100, entry * cfg["tp"] * atr_pct / 100
    dec = 3 if entry > 20 else 5
    if direction == "LONG":
        return round(entry - sl_d, dec), round(entry + tp_d, dec)
    return round(entry + sl_d, dec), round(entry - tp_d, dec)


def plan_for(db: Session, rec: SignalRecord) -> SignalPlan:
    plan = db.scalar(select(SignalPlan).where(SignalPlan.signal_id == rec.id))
    if plan is not None:
        return plan
    tt, why = classify(db, rec)
    plan = SignalPlan(signal_id=rec.id, trade_type=tt, type_reason=why)
    if rec.entry_price:
        plan.atr_pct = typical_move_pct(db, rec.asset, _aware(rec.opened_at))
        if plan.atr_pct:
            plan.stop_loss, plan.take_profit = levels(rec.entry_price, rec.direction, tt, plan.atr_pct)
    db.add(plan)
    db.flush()
    return plan


def check_plan(db: Session, rec: SignalRecord, plan: SignalPlan, now: datetime) -> None:
    """Which came first after the call: the take profit or the stop loss? Uses stored prices (closes when only
    daily data exist, so a level touched intraday but not closed beyond may be missed)."""
    if plan.outcome or not rec.entry_price or plan.stop_loss is None or plan.take_profit is None:
        return
    opened = _aware(rec.opened_at)
    if plan.trade_type == "day":  # closed at the end of that day (UTC), giving it at least 8 hours
        end = max(datetime.combine(opened.date(), datetime.max.time(), tzinfo=timezone.utc), opened + timedelta(hours=8))
    else:
        end = opened + timedelta(days=PLAN["swing"]["days"])
    long = rec.direction == "LONG"
    risk = abs(rec.entry_price - plan.stop_loss) or None
    last = None
    for ts, px in _prices_between(db, rec.asset, opened, min(end, now)):
        last = (ts, px)
        if (px >= plan.take_profit) if long else (px <= plan.take_profit):
            plan.outcome, plan.outcome_at = "target", ts
            plan.result_r = round(abs(plan.take_profit - rec.entry_price) / risk, 2) if risk else None
            return
        if (px <= plan.stop_loss) if long else (px >= plan.stop_loss):
            plan.outcome, plan.outcome_at = "stop", ts
            plan.result_r = -1.0
            return
    if now >= end and last is not None and risk:
        plan.outcome, plan.outcome_at = "expired", last[0]
        plan.result_r = round(((last[1] - rec.entry_price) if long else (rec.entry_price - last[1])) / risk, 2)


def edit_plan(db: Session, signal_id: int, trade_type: str | None = None, stop_loss: float | None = None,
              take_profit: float | None = None) -> dict:
    rec = db.get(SignalRecord, signal_id)
    if rec is None:
        raise LookupError("No such call")
    plan = plan_for(db, rec)
    if trade_type is not None:
        if trade_type not in PLAN:
            raise ValueError("Trade type must be swing or day")
        plan.trade_type, plan.type_reason = trade_type, "Set by hand"
        if stop_loss is None and take_profit is None and rec.entry_price and plan.atr_pct and not plan.manual:
            plan.stop_loss, plan.take_profit = levels(rec.entry_price, rec.direction, trade_type, plan.atr_pct)
    for name, v in (("stop_loss", stop_loss), ("take_profit", take_profit)):
        if v is not None:
            if v <= 0:
                db.rollback()
                raise ValueError("Levels must be positive prices")
            setattr(plan, name, v)
            plan.manual = True
    if rec.entry_price and plan.stop_loss is not None and plan.take_profit is not None:
        long = rec.direction == "LONG"
        if (plan.stop_loss >= rec.entry_price) if long else (plan.stop_loss <= rec.entry_price):
            db.rollback()
            raise ValueError(f"The stop loss must be {'below' if long else 'above'} the entry ({rec.entry_price}) for a {'buy' if long else 'sell'}")
        if (plan.take_profit <= rec.entry_price) if long else (plan.take_profit >= rec.entry_price):
            db.rollback()
            raise ValueError(f"The take profit must be {'above' if long else 'below'} the entry ({rec.entry_price}) for a {'buy' if long else 'sell'}")
    plan.outcome = plan.outcome_at = plan.result_r = None  # re-checked with the new levels
    check_plan(db, rec, plan, utcnow())
    db.commit()
    return _plan_json(rec, plan)


def _plan_json(rec: SignalRecord, plan: SignalPlan | None) -> dict:
    if plan is None:
        return {"trade_type": None}
    e = rec.entry_price
    pct = (lambda lvl: None if not e or lvl is None else round(abs(lvl / e - 1) * 100, 2))
    rr = (round(abs(plan.take_profit - e) / abs(e - plan.stop_loss), 2)
          if e and plan.stop_loss is not None and plan.take_profit is not None and e != plan.stop_loss else None)
    return {"trade_type": plan.trade_type, "type_reason": plan.type_reason, "stop_loss": plan.stop_loss,
            "take_profit": plan.take_profit, "sl_pct": pct(plan.stop_loss), "tp_pct": pct(plan.take_profit),
            "risk_reward": rr, "atr_pct": plan.atr_pct, "manual": plan.manual, "outcome": plan.outcome,
            "outcome_at": _aware(plan.outcome_at).isoformat() if plan.outcome_at else None, "result_r": plan.result_r}


# --------------------------------------------------------------------------- one call's full setup (for its chart)

MAX_PATH_POINTS = 600


def _path(db: Session, asset: str, start: datetime, end: datetime, thin: bool = True) -> list[tuple[datetime, float]]:
    """Prices from `start` to `end` for the call's chart: every stored price (hourly where available); daily
    closes when fewer than 10 are stored (e.g. crosses built from their USD legs). Thinned to MAX_PATH_POINTS."""
    pts = [(_aware(ts), px) for ts, px in db.execute(
        select(MarketPrice.ts, MarketPrice.price).where(MarketPrice.symbol == asset, MarketPrice.ts >= start,
                                                        MarketPrice.ts <= end).order_by(MarketPrice.ts))]
    if len(pts) < 10:
        daily = []
        for d, v in sorted(_series(db, asset).items()):
            ts = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=21)
            if start <= ts <= end and v:
                daily.append((ts, v))
        if len(daily) > len(pts):
            pts = daily
    if thin and len(pts) > MAX_PATH_POINTS:
        step = -(-len(pts) // MAX_PATH_POINTS)
        pts = pts[::step] + ([pts[-1]] if (len(pts) - 1) % step else [])
    return pts


MAX_BARS = 160
BAR_HOURS = (1, 2, 4, 6, 8, 12, 24)


def _bars(pts: list[tuple[datetime, float]], start: datetime, end: datetime, min_per_bar: float) -> tuple[int, list[list]]:
    """Candles built from stored closes: the smallest bar size (hours) giving at most MAX_BARS bars with about
    `min_per_bar` prices in each. Open = the previous bar's close, so gaps between bars don't break the chain;
    high / low are the highest and lowest stored prices, so wicks between two stored prices are not seen."""
    if len(pts) < 2:
        return 24, []
    span_h = max(1.0, (end - start).total_seconds() / 3600)
    hours = BAR_HOURS[-1]
    for hrs in BAR_HOURS:
        n = span_h / hrs
        if n <= MAX_BARS and len(pts) / n >= min_per_bar:
            hours = hrs
            break
    size = hours * 3600
    epoch = datetime(2000, 1, 1, tzinfo=timezone.utc)
    buckets: dict[int, list[float]] = {}
    for ts, px in pts:
        buckets.setdefault(int((ts - epoch).total_seconds() // size), []).append(px)
    out, prev = [], None
    for k in sorted(buckets):
        v = buckets[k]
        o = prev if prev is not None else v[0]
        out.append([(epoch + timedelta(seconds=k * size)).isoformat(), o, max(o, *v), min(o, *v), v[-1]])
        prev = v[-1]
    return hours, out


def _snapshot(db: Session, rec: SignalRecord) -> dict | None:
    """The trade setup the engine stored when the call was made (latest at or just before it)."""
    from app.analytics.trading import FACTOR_WEIGHTS, LABELS
    from app.models import TradeSetup

    at = _aware(rec.opened_at) + timedelta(minutes=2)
    q = select(TradeSetup).where(TradeSetup.asset == rec.asset, TradeSetup.as_of <= at)
    s = (db.scalar(q.where(TradeSetup.grade == rec.grade, TradeSetup.direction == rec.direction)
                   .order_by(TradeSetup.as_of.desc(), TradeSetup.id.desc()))
         or db.scalar(q.order_by(TradeSetup.as_of.desc(), TradeSetup.id.desc())))
    if s is None:
        return None
    weights = {LABELS[k]: w for k, w in FACTOR_WEIGHTS.items()}
    factors = [{"name": k, "score": round(v, 1), "max": weights.get(k)}
               for k, v in sorted((s.factors or {}).items(), key=lambda kv: -abs(kv[1] or 0)) if v is not None]
    return {"as_of": _aware(s.as_of).isoformat(), "grade": s.grade, "direction": s.direction,
            "confluence": s.confluence_score, "factors": factors, "primary_driver": s.primary_driver,
            "secondary_drivers": s.secondary_drivers or [], "catalysts": s.catalysts or [],
            "confirmation": s.confirmation or [], "invalidation": s.invalidation or [], "risks": s.risks or [],
            "alternative": s.alternative, "data_status": s.data_status, "grade_cap_reason": s.grade_cap_reason}


def setup_detail(db: Session, signal_id: int, now: datetime | None = None) -> dict:
    """Everything needed to draw one call: the price path around it, its levels and outcome, and the setup
    (factor scores, drivers, confirmation / invalidation) as it stood when the call was given."""
    now = now or utcnow()
    rec = db.get(SignalRecord, signal_id)
    if rec is None:
        raise LookupError("No such call")
    plan = plan_for(db, rec)
    check_plan(db, rec, plan, now)
    db.commit()
    opened = _aware(rec.opened_at)
    day = plan.trade_type == "day"
    start = opened - (timedelta(days=2) if day else timedelta(days=15))
    trade_end = (max(datetime.combine(opened.date(), datetime.max.time(), tzinfo=timezone.utc), opened + timedelta(hours=8))
                 if day else opened + timedelta(days=PLAN["swing"]["days"]))
    after = _aware(plan.outcome_at) if plan.outcome_at else min(trade_end, now)
    end = min(now, after + (timedelta(hours=12) if day else timedelta(days=3)))
    raw = _path(db, rec.asset, start, max(end, opened), thin=False)
    bar_hours, bars = _bars(raw, start, max(end, opened), 2 if day else 3)
    pts = _path(db, rec.asset, start, max(end, opened))
    call = {"id": rec.id, "asset": rec.asset, "direction": rec.direction, "grade": rec.grade,
            "confluence": rec.confluence, "opened_at": opened.isoformat(), "entry_price": rec.entry_price,
            "open": rec.superseded_at is None, "note": rec.note,
            "superseded_at": _aware(rec.superseded_at).isoformat() if rec.superseded_at else None} | _plan_json(rec, plan)
    return {"call": call, "prices": [[ts.isoformat(), px] for ts, px in pts], "bars": bars, "bar_hours": bar_hours,
            "window": {"start": start.isoformat(), "end": end.isoformat(), "trade_end": trade_end.isoformat()},
            "setup": _snapshot(db, rec),
            "note": "Built from stored prices (hourly where available, daily closes otherwise): each candle opens at the "
                    "previous close and its wicks are the highest and lowest stored prices, so a level touched between "
                    "two stored prices may not show. The setup is the analysis as it stood when the call was given."}


def summary(db: Session) -> dict:
    recs = list(db.scalars(select(SignalRecord).order_by(SignalRecord.opened_at.desc())))
    now = utcnow()
    plans = {p.signal_id: p for p in db.scalars(select(SignalPlan))}
    for r in recs[:200]:
        if r.id not in plans:
            plans[r.id] = plan_for(db, r)
        check_plan(db, r, plans[r.id], now)
    db.commit()
    by_grade = []
    for g in GRADED:
        rs = [r for r in recs if r.grade == g]
        row = {"grade": g, "signals": len(rs)}
        for field, days in HORIZONS.items():
            vals = [getattr(r, field) for r in rs if getattr(r, field) is not None]
            row[f"n_{days}d"] = len(vals)
            row[f"hit_rate_{days}d"] = round(100 * sum(v > 0 for v in vals) / len(vals), 1) if vals else None
            row[f"avg_move_{days}d"] = round(sum(vals) / len(vals), 3) if vals else None
        ps = [plans[r.id] for r in rs if r.id in plans and plans[r.id].outcome]
        row["targets_hit"] = sum(p.outcome == "target" for p in ps)
        row["stopped_out"] = sum(p.outcome == "stop" for p in ps)
        row["avg_r"] = round(sum(p.result_r or 0 for p in ps) / len(ps), 2) if ps else None
        by_grade.append(row)
    recent = [{"id": r.id, "asset": r.asset, "direction": r.direction, "grade": r.grade,
               "confluence": r.confluence, "opened_at": _aware(r.opened_at).isoformat(), "entry_price": r.entry_price,
               "ret_1d": r.ret_1d, "ret_5d": r.ret_5d, "ret_20d": r.ret_20d,
               "open": r.superseded_at is None, "note": r.note} | _plan_json(r, plans.get(r.id)) for r in recs[:200]]
    evaluated = sum(1 for r in recs if r.ret_5d is not None)
    return {"by_grade": by_grade, "recent": recent, "total_signals": len(recs), "evaluated_5d": evaluated,
            "enough_data": evaluated >= 30,
            "note": "A grade is only worth trusting once it has 30+ evaluated calls with a hit rate clearly "
                    "above 50% and a positive average move. Moves are measured in the call's direction, "
                    "before costs.",
            "plan_note": "Stop loss and take profit are sized from the pair's typical daily move over the last 14 days: "
                         "swing trades 1.5x for the stop and 3x for the target (held up to 20 days), day trades 0.5x and 1x "
                         "(closed the same day). Both aim for 1 : 2 risk-reward. Results are in R: +2R = made twice the risk, "
                         "−1R = stopped out."}
