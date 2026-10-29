"""Equities on the Markets page: Finnhub quotes (free key: real-time US stocks and ETFs, 60 calls a minute).

Index levels (S&P 500 etc.) need a paid Finnhub plan, so the indices and countries are shown through the
ETFs that track them (SPY = S&P 500, EWJ = Japan...). Each quote is also stored as a price point, so 1-week
and 1-month changes build up over time.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import utcnow
from app.ingestion.base import SourceUnavailable, http_get
from app.models import EquityQuote, EquityWatch, MarketPrice, Source

# group -> [(symbol, name, currency it relates to)]
GROUPS: dict[str, list[tuple[str, str, str | None]]] = {
    "US indices": [("SPY", "S&P 500 (SPY)", "USD"), ("QQQ", "Nasdaq 100 (QQQ)", "USD"), ("DIA", "Dow Jones (DIA)", "USD"),
                   ("IWM", "Russell 2000 small caps (IWM)", "USD")],
    "Sectors": [("XLK", "Technology", None), ("XLF", "Financials", None), ("XLE", "Energy", None),
                ("XLV", "Health care", None), ("XLY", "Consumer discretionary", None), ("XLP", "Consumer staples", None),
                ("XLI", "Industrials", None), ("XLU", "Utilities", None), ("XLB", "Materials", None),
                ("XLRE", "Real estate", None), ("XLC", "Communication", None)],
    "World": [("VGK", "Europe", "EUR"), ("EWG", "Germany", "EUR"), ("EWU", "United Kingdom", "GBP"),
              ("EWJ", "Japan", "JPY"), ("EWL", "Switzerland", "CHF"), ("EWC", "Canada", "CAD"),
              ("EWA", "Australia", "AUD"), ("ENZL", "New Zealand", "NZD"), ("EZA", "South Africa", "ZAR"),
              ("EWW", "Mexico", "MXN"), ("FXI", "China large caps", "CNY"), ("EEM", "Emerging markets", None)],
    "Mega caps": [("AAPL", "Apple", None), ("MSFT", "Microsoft", None), ("NVDA", "Nvidia", None),
                  ("AMZN", "Amazon", None), ("GOOGL", "Alphabet", None), ("META", "Meta", None),
                  ("TSLA", "Tesla", None), ("JPM", "JPMorgan", None)],
}
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")


def all_symbols(db: Session) -> list[tuple[str, str, str, str | None]]:
    out = [(s, n, g, c) for g, items in GROUPS.items() for s, n, c in items]
    known = {s for s, *_ in out}
    for w in db.scalars(select(EquityWatch).order_by(EquityWatch.added_at)):
        if w.symbol not in known:
            out.append((w.symbol, w.name or w.symbol, "My list", None))
    return out


def fetch_quote(symbol: str) -> dict:
    r = http_get("https://finnhub.io/api/v1/quote", {"symbol": symbol, "token": settings.finnhub_api_key}, retries=1)
    return r.json() or {}


def run_equities(db: Session, src: Source) -> int:
    if not settings.finnhub_api_key:
        raise SourceUnavailable("Set FINNHUB_API_KEY (free key from finnhub.io) on api and worker")
    delay = float(os.getenv("FINNHUB_DELAY", "1.1"))  # free plan: 60 calls a minute
    n, ok, bad = 0, 0, []
    for i, (sym, _, _, cls) in enumerate(all_symbols(db)):
        if i and delay:
            time.sleep(delay)
        try:
            q = fetch_quote(sym)
        except Exception as exc:
            bad.append(f"{sym}: {exc.__class__.__name__}")
            continue
        price = q.get("c")
        if not price:  # unknown ticker or not on the free plan: Finnhub returns zeros
            bad.append(f"{sym}: no quote")
            continue
        ok += 1
        ts = datetime.fromtimestamp(q["t"], tz=timezone.utc) if q.get("t") else utcnow()
        row = db.get(EquityQuote, sym) or EquityQuote(symbol=sym)
        row.price, row.change, row.change_pct = price, q.get("d"), q.get("dp")
        row.open, row.high, row.low, row.prev_close = q.get("o"), q.get("h"), q.get("l"), q.get("pc")
        row.quote_time, row.fetched_at = ts, utcnow()
        db.merge(row)
        if db.get(MarketPrice, (sym, ts)) is None:
            db.add(MarketPrice(symbol=sym, ts=ts, price=price, asset_class="equity", source="finnhub"))
            n += 1
        db.commit()
    if not ok:
        raise SourceUnavailable("Finnhub returned no quotes. " + ("; ".join(bad[:3]) if bad else ""))
    return (n, "No quote for: " + ", ".join(b.split(":")[0] for b in bad)) if bad else n


def _aware(t):
    return t if t is None or t.tzinfo else t.replace(tzinfo=timezone.utc)


def _change_since(db: Session, sym: str, price: float, days: int) -> float | None:
    ref = db.scalar(select(MarketPrice).where(MarketPrice.symbol == sym,
                                              MarketPrice.ts <= utcnow() - timedelta(days=days))
                    .order_by(MarketPrice.ts.desc()))
    return round((price / ref.price - 1) * 100, 2) if ref and ref.price else None


def board(db: Session) -> dict:
    rows = []
    for sym, name, group, ccy in all_symbols(db):
        q = db.get(EquityQuote, sym)
        rows.append({"symbol": sym, "name": name, "group": group, "currency": ccy,
                     "price": q.price if q else None, "change": q.change if q else None,
                     "change_pct": q.change_pct if q else None, "open": q.open if q else None,
                     "high": q.high if q else None, "low": q.low if q else None,
                     "prev_close": q.prev_close if q else None,
                     "quote_time": _aware(q.quote_time).isoformat() if q and q.quote_time else None,
                     "change_1w_pct": _change_since(db, sym, q.price, 7) if q and q.price else None,
                     "change_1m_pct": _change_since(db, sym, q.price, 30) if q and q.price else None,
                     "custom": group == "My list"})
    groups = list(GROUPS) + (["My list"] if any(r["custom"] for r in rows) else [])
    have = [r for r in rows if r["change_pct"] is not None]
    breadth = {"up": sum(r["change_pct"] > 0 for r in have), "down": sum(r["change_pct"] < 0 for r in have)}
    return {"rows": rows, "groups": groups, "breadth": breadth, "has_key": bool(settings.finnhub_api_key)}


def add_symbol(db: Session, symbol: str, name: str | None = None) -> EquityWatch:
    s = symbol.strip().upper()
    if not SYMBOL_RE.match(s):
        raise ValueError("Use a US ticker like AAPL or BRK.B")
    w = db.get(EquityWatch, s) or EquityWatch(symbol=s, name=(name or "").strip() or None)
    db.merge(w)
    db.commit()
    if settings.finnhub_api_key:  # fetch its quote straight away so it shows at once
        try:
            q = fetch_quote(s)
            if q.get("c"):
                db.merge(EquityQuote(symbol=s, price=q["c"], change=q.get("d"), change_pct=q.get("dp"), open=q.get("o"),
                                     high=q.get("h"), low=q.get("l"), prev_close=q.get("pc"),
                                     quote_time=datetime.fromtimestamp(q["t"], tz=timezone.utc) if q.get("t") else utcnow(),
                                     fetched_at=utcnow()))
                db.commit()
        except Exception:
            db.rollback()
    return w


def remove_symbol(db: Session, symbol: str) -> None:
    w = db.get(EquityWatch, symbol.upper())
    if w:
        db.delete(w)
        q = db.get(EquityQuote, symbol.upper())
        if q:
            db.delete(q)
        db.commit()
