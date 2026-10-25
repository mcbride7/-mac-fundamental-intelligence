"""Economic heatmap per currency (Macro page).

For every tracked indicator of a currency, the latest release is read and the surprise
(actual - forecast, or your own surprise typed on the calendar) is turned into two calls:

  Currency impact - a hawkish surprise (more pressure for higher rates) is Bullish for the currency.
                    Whether "higher" is hawkish comes from each indicator's setting: higher inflation,
                    growth or payrolls is hawkish, higher unemployment or jobless claims is dovish.
  Stocks impact   - stronger growth, jobs, spending or business data is Bullish for the country's stocks;
                    hotter inflation or a hawkish rate surprise is Bearish (higher rates hurt valuations).

Scores: each Bullish row counts +1 and each Bearish row -1. The "bullish %" gauges are the share of rows
that are Bullish. Currency pairs compare the two currencies' scores (base minus quote). Gold and silver
lean against the US dollar's score; oil and the stock index follow the stocks score.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EconomicEvent, EconomicSurprise, Indicator
from app.services import data_access as da

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN", "CNY"]
STOCK_INDEX = {"USD": "SPX500", "EUR": "EU STOXX 50", "GBP": "FTSE 100", "JPY": "Nikkei 225", "CHF": "SMI",
               "CAD": "TSX", "AUD": "ASX 200", "NZD": "NZX 50", "ZAR": "JSE Top 40", "MXN": "IPC Mexico",
               "CNY": "CSI 300"}
# usual market quoting order, so pairs read the normal way (EURUSD, not USDEUR)
ORDER = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY", "ZAR", "MXN", "CNY"]
INVERSE_FOR_STOCKS = {"inflation", "monetary_policy"}
CATEGORY_ORDER = {"growth": 0, "business": 1, "consumers": 2, "inflation": 3, "employment": 4,
                  "monetary_policy": 5}
IMPORTANCE = {"high": 0, "medium": 1, "low": 2}


def _aware(ts):
    return ts if ts is None or ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def currency_call(surprise: float | None, higher_is: str) -> str:
    if surprise is None or abs(surprise) < 1e-9 or higher_is == "neutral":
        return "Neutral"
    hawkish = surprise > 0 if higher_is == "hawkish" else surprise < 0
    return "Bullish" if hawkish else "Bearish"


def stocks_call(currency_impact: str, category: str) -> str:
    if currency_impact == "Neutral":
        return "Neutral"
    if category in INVERSE_FOR_STOCKS:
        return "Bearish" if currency_impact == "Bullish" else "Bullish"
    return currency_impact


def _pts(call: str) -> int:
    return 1 if call == "Bullish" else -1 if call == "Bearish" else 0


def rows_for(db: Session, currency: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    inds = list(db.scalars(select(Indicator).where(Indicator.currency == currency)))
    inds.sort(key=lambda i: (CATEGORY_ORDER.get(i.category, 9), IMPORTANCE.get(i.importance, 3), i.name))
    out = []
    for ind in inds:
        rel = da.latest_current(db, ind.id)
        if rel is None:
            continue
        ev = db.get(EconomicEvent, rel.event_id) if rel.event_id else da.event_for(db, ind.id, rel.reference_period)
        forecast = rel.consensus if rel.consensus is not None else (ev.consensus if ev else None)
        previous = rel.previous if rel.previous is not None else (ev.previous if ev else None)
        if previous is None:
            earlier = [r for r in da.current_series(db, ind.id, 24) if r.reference_period < rel.reference_period]
            previous = earlier[-1].actual if earlier else None
        s = db.scalar(select(EconomicSurprise).where(EconomicSurprise.release_id == rel.id))
        surprise = s.market_surprise if s and s.market_surprise is not None else (
            round(rel.actual - forecast, 4) if forecast is not None else None)
        when = _aware(rel.released_at) or (_aware(ev.scheduled_at) if ev else None) or _aware(rel.created_at)
        cur = currency_call(surprise, ind.higher_is)
        out.append({
            "indicator": ind.code, "name": ind.name, "category": ind.category, "importance": ind.importance,
            "period": rel.reference_period, "date": when, "new": bool(when and now - when <= timedelta(days=2)),
            "surprise": surprise, "actual": rel.actual, "forecast": forecast, "previous": previous,
            "unit": ind.unit, "higher_is": ind.higher_is,
            "currency_impact": cur, "stocks_impact": stocks_call(cur, ind.category),
            "status": rel.verification_status, "event_id": ev.id if ev else None,
        })
    return out


def _score(rows: list[dict], key: str) -> int:
    return sum(_pts(r[key]) for r in rows)


def _pct(rows: list[dict], key: str) -> float | None:
    if not rows:
        return None
    return round(100 * sum(1 for r in rows if r[key] == "Bullish") / len(rows), 2)


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if ORDER.index(a) < ORDER.index(b) else (b, a)


def heatmap(db: Session, currency: str) -> dict:
    currency = currency.upper()
    if currency not in CURRENCIES:
        raise LookupError(f"Unknown currency {currency}")
    all_rows = {c: rows_for(db, c) for c in CURRENCIES}
    rows = all_rows[currency]
    cur_score = {c: _score(r, "currency_impact") for c, r in all_rows.items()}
    stocks_score = _score(rows, "stocks_impact")

    assets = [{"asset": STOCK_INDEX[currency], "score": stocks_score, "basis": "stocks impact"}]
    if currency == "USD":
        assets = [{"asset": "GOLD", "score": -cur_score["USD"], "basis": "opposite of the dollar"},
                  {"asset": "SILVER", "score": -cur_score["USD"], "basis": "opposite of the dollar"},
                  {"asset": "USOIL", "score": stocks_score, "basis": "US growth (stocks impact)"}] + assets
    pairs = []
    for other in CURRENCIES:
        if other == currency or not all_rows[other]:
            continue
        base, quote = _pair(currency, other)
        pairs.append({"pair": base + quote, "score": cur_score[base] - cur_score[quote],
                      "base_score": cur_score[base], "quote_score": cur_score[quote]})
    pairs.sort(key=lambda p: -abs(p["score"]))
    assets.sort(key=lambda a: -a["score"])
    return {
        "currency": currency, "rows": rows,
        "currency_bullish_pct": _pct(rows, "currency_impact"), "stocks_bullish_pct": _pct(rows, "stocks_impact"),
        "currency_score": cur_score[currency], "stocks_score": stocks_score,
        "stock_index": STOCK_INDEX[currency], "assets": assets, "pairs": pairs,
        "tabs": [{"currency": c, "rows": len(r), "score": cur_score[c]} for c, r in all_rows.items()],
    }
