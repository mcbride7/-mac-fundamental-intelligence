"""Track record of the app's trade grades.

Each time an asset gets a new graded call (a different grade or direction from its last one),
the call is frozen with the price at that moment. 1, 5 and 20 days later the price is checked
again and the move in the call's direction is stored. The summary shows, per grade, how often the
call was right and the average move, so the grades can be judged on evidence rather than trust."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import MarketPrice
from app.models.track import SignalRecord

HORIZONS = {"ret_1d": 1, "ret_5d": 5, "ret_20d": 20}
GRADED = ("A+", "A", "B", "C")
MAX_PRICE_GAP = timedelta(days=4)  # weekends and holidays


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _price_near(db: Session, asset: str, ts: datetime) -> MarketPrice | None:
    p = db.scalar(select(MarketPrice).where(MarketPrice.symbol == asset, MarketPrice.ts <= ts)
                  .order_by(MarketPrice.ts.desc()))
    if p is not None and ts - _aware(p.ts) <= MAX_PRICE_GAP:
        return p
    return None


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


def summary(db: Session) -> dict:
    recs = list(db.scalars(select(SignalRecord).order_by(SignalRecord.opened_at.desc())))
    by_grade = []
    for g in GRADED:
        rs = [r for r in recs if r.grade == g]
        row = {"grade": g, "signals": len(rs)}
        for field, days in HORIZONS.items():
            vals = [getattr(r, field) for r in rs if getattr(r, field) is not None]
            row[f"n_{days}d"] = len(vals)
            row[f"hit_rate_{days}d"] = round(100 * sum(v > 0 for v in vals) / len(vals), 1) if vals else None
            row[f"avg_move_{days}d"] = round(sum(vals) / len(vals), 3) if vals else None
        by_grade.append(row)
    recent = [{"id": r.id, "asset": r.asset, "direction": r.direction, "grade": r.grade,
               "confluence": r.confluence, "opened_at": _aware(r.opened_at).isoformat(), "entry_price": r.entry_price,
               "ret_1d": r.ret_1d, "ret_5d": r.ret_5d, "ret_20d": r.ret_20d,
               "open": r.superseded_at is None, "note": r.note} for r in recs[:200]]
    evaluated = sum(1 for r in recs if r.ret_5d is not None)
    return {"by_grade": by_grade, "recent": recent, "total_signals": len(recs), "evaluated_5d": evaluated,
            "enough_data": evaluated >= 30,
            "note": "A grade is only worth trusting once it has 30+ evaluated calls with a hit rate clearly "
                    "above 50% and a positive average move. Moves are measured in the call's direction, "
                    "before costs."}
