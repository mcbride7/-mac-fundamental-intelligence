"""Business surveys (manufacturing and services PMIs) and consumer confidence, per currency (Macro page).

PMIs: 50 separates expansion from contraction, so each reading is judged on three things:
  level     - above 50 is expansion (supportive), below 50 is contraction
  momentum  - up or down on the previous month
  surprise  - above or below the forecast
Consumer confidence has no common 50 line (each survey has its own scale), so it is judged on its
momentum, its surprise and where it sits against its own average over the last 12 readings.

Each signal counts +1 (supportive for the currency and growth) or -1; the sum gives a lean.
"""
from __future__ import annotations

import re
import statistics

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import EconomicEvent, Indicator
from app.services import data_access as da
from app.services import heatmap
from app.services.setups_table import column_of

KINDS = {"mpmi": "Manufacturing PMI", "spmi": "Services PMI", "conf": "Consumer confidence"}


def kind_of(ind: Indicator) -> str | None:
    k = column_of(ind.code, ind.category)
    return k if k in KINDS else None


def _sign(x: float | None, eps: float = 1e-9) -> int:
    return 0 if x is None or abs(x) < eps else (1 if x > 0 else -1)


def analyse(kind: str, actual: float, previous: float | None, forecast: float | None,
            history: list[float]) -> dict:
    """Signals and a plain-English read for one reading."""
    change = None if previous is None else round(actual - previous, 2)
    surprise = None if forecast is None else round(actual - forecast, 2)
    signals: dict[str, int] = {"momentum": _sign(change), "surprise": _sign(surprise)}
    words = []
    if kind in ("mpmi", "spmi"):
        signals["level"] = _sign(actual - 50)
        state = "expansion" if actual > 50 else "contraction" if actual < 50 else "no change (50)"
        if previous is not None and (previous - 50) * (actual - 50) < 0:
            words.append(f"crossed into {state}")
        else:
            words.append(f"in {state}")
    else:
        avg = statistics.fmean(history[-12:]) if len(history) >= 3 else None
        signals["level"] = _sign(None if avg is None else actual - avg)
        state = None if avg is None else ("above" if actual > avg else "below" if actual < avg else "at")
        if state:
            words.append(f"{state} its 12-reading average ({avg:.1f})")
    if change is not None:
        words.append("improving" if change > 0 else "worsening" if change < 0 else "unchanged")
    if surprise is not None:
        words.append("beat forecast" if surprise > 0 else "missed forecast" if surprise < 0 else "in line")
    score = sum(signals.values())
    lean = "Bullish" if score >= 2 else "Bearish" if score <= -2 else "Mixed" if score == 0 and any(signals.values()) \
        else ("Leaning bullish" if score > 0 else "Leaning bearish" if score < 0 else "Neutral")
    return {"change": change, "surprise": surprise, "signals": signals, "score": score, "lean": lean,
            "read": ", ".join(words).capitalize() if words else ""}


def row_for(db: Session, ind: Indicator) -> dict:
    kind = kind_of(ind)
    base = {"indicator": ind.code, "name": ind.name, "currency": ind.currency, "kind": kind,
            "frequency": ind.frequency, "importance": ind.importance, "actual": None}
    series = da.current_series(db, ind.id, 24)
    nxt = db.scalar(select(EconomicEvent).where(EconomicEvent.indicator_id == ind.id,
                                                EconomicEvent.scheduled_at >= utcnow())
                    .order_by(EconomicEvent.scheduled_at))
    if nxt is not None:
        base["next"] = {"date": nxt.scheduled_at, "period": nxt.reference_period, "forecast": nxt.consensus,
                        "event_id": nxt.id}
    if not series:
        return base
    rel = series[-1]
    ev = db.get(EconomicEvent, rel.event_id) if rel.event_id else da.event_for(db, ind.id, rel.reference_period)
    forecast = rel.consensus if rel.consensus is not None else (ev.consensus if ev else None)
    previous = series[-2].actual if len(series) > 1 else (rel.previous if rel.previous is not None
                                                          else (ev.previous if ev else None))
    hist = [r.actual for r in series]
    return base | {"period": rel.reference_period, "actual": rel.actual, "previous": previous, "forecast": forecast,
                   "status": rel.verification_status, "event_id": ev.id if ev else None,
                   "history": [{"period": r.reference_period, "value": r.actual} for r in series[-12:]],
                   **analyse(kind, rel.actual, previous, forecast, hist[:-1] or hist)}


def board(db: Session) -> dict:
    inds = [i for i in db.scalars(select(Indicator)) if kind_of(i)]
    order = {c: n for n, c in enumerate(heatmap.CURRENCIES)}
    inds.sort(key=lambda i: (order.get(i.currency, 99), heatmap.IMPORTANCE.get(i.importance, 3), i.name))
    rows = [row_for(db, i) for i in inds]
    kinds = {}
    for k, label in KINDS.items():
        rs = [r for r in rows if r["kind"] == k]
        have = [r for r in rs if r["actual"] is not None]
        out = {"label": label, "rows": rs, "with_data": len(have)}
        if k != "conf":
            out["expanding"] = sum(1 for r in have if r["actual"] > 50)
            out["contracting"] = sum(1 for r in have if r["actual"] < 50)
        out["improving"] = sum(1 for r in have if (r.get("change") or 0) > 0)
        out["worsening"] = sum(1 for r in have if (r.get("change") or 0) < 0)
        kinds[k] = out
    per_ccy = {}
    for c in heatmap.CURRENCIES:
        rs = [r for r in rows if r["currency"] == c and r["actual"] is not None]
        if rs:
            # one vote per kind: the most important indicator of that kind
            score = 0
            for k in KINDS:
                first = next((r for r in rs if r["kind"] == k), None)
                score += 0 if first is None else max(-1, min(1, first["score"]))
            per_ccy[c] = score
    return {"kinds": kinds, "currency_scores": per_ccy}


def edit(db: Session, code: str, value, period: str | None, reason: str | None, user_id: int | None) -> dict:
    """Type in a reading from the Macro page (same checks as the calendar; unusual values ask for a reason)."""
    from app.services import macro_edit

    ind = da.indicator_by_code(db, code)
    if ind is None or not kind_of(ind):
        raise LookupError(f"Unknown survey indicator {code}")
    res = macro_edit.edit(db, code, "actual", value, period, reason, user_id)
    return res | {"value": res.get("value")}
