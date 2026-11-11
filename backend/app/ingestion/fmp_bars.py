"""FMP price bars (Starter plan): daily (5 years) and hourly (last ~13 months) open/high/low/close/volume for forex
and metals. The hourly bars are combined into 4-hour candles for the supply & demand strategy.

Used by the Track record to check stops and targets against each bar's real high and low, and to size them from the
true average daily range (ATR) instead of close-to-close moves.
"""
from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.base import SourceUnavailable
from app.models import Source
from app.models.track import PriceBar

BASE = "https://financialmodelingprep.com/stable"
NY = ZoneInfo("America/New_York")  # FMP's intraday timestamps are New York time
SYMBOLS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD", "NZDUSD", "USDZAR", "USDMXN", "USDCNH",
    "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURNZD", "EURCAD", "GBPJPY", "GBPCHF", "GBPAUD", "GBPNZD", "GBPCAD",
    "AUDJPY", "AUDNZD", "NZDJPY", "CADJPY", "CHFJPY", "XAUUSD", "XAGUSD",
]
ALIASES = {"XAUUSD": ["XAUUSD", "GCUSD"], "XAGUSD": ["XAGUSD", "SIUSD"]}  # forex symbol first, then the futures one


def _get(path: str, params: dict) -> list:
    import requests

    r = requests.get(f"{BASE}/{path}", params=params | {"apikey": settings.fmp_api_key}, timeout=30)
    try:
        body = r.json()
    except ValueError:
        body = None
    msg = body.get("Error Message") or body.get("message") if isinstance(body, dict) else None
    if r.status_code == 401 or (msg and "invalid" in msg.lower() and "key" in msg.lower()):
        raise PermissionError("FMP rejected the API key: check FMP_API_KEY in Railway")
    if r.status_code in (402, 403) or (msg and any(w in msg.lower() for w in ("subscription", "premium", "restricted"))):
        raise LookupError("not on your FMP plan")
    if r.status_code == 429 or (msg and "limit" in msg.lower()):
        raise SourceUnavailable("FMP request limit reached; it will retry later")
    if r.status_code >= 400:
        raise LookupError(f"FMP {r.status_code}: {(msg or r.text[:100]).strip()}")
    if isinstance(body, dict):  # some endpoints wrap the list
        body = body.get("historical") or body.get("data") or []
    return body if isinstance(body, list) else []


def parse_bar_time(raw: str, interval: str) -> datetime | None:
    try:
        if interval == "1day":
            return datetime.combine(date.fromisoformat(raw[:10]), datetime.min.time(), tzinfo=timezone.utc)
        return datetime.fromisoformat(raw.replace(" ", "T")[:19]).replace(tzinfo=NY).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def save_bars(db: Session, symbol: str, interval: str, rows: list) -> int:
    n = 0
    for x in rows:
        if not isinstance(x, dict):
            continue
        ts = parse_bar_time(str(x.get("date") or ""), interval)
        try:
            o, h, lo, c = (float(x[k]) for k in ("open", "high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        if ts is None or not (lo <= min(o, c) and h >= max(o, c)):
            continue
        try:
            vol = float(x.get("volume")) if x.get("volume") is not None else None
        except (TypeError, ValueError):
            vol = None
        db.merge(PriceBar(symbol=symbol, interval=interval, ts=ts, open=o, high=h, low=lo, close=c, volume=vol,
                          source="fmp"))
        n += 1
    return n


def _fetch(symbol: str, interval: str, start: date, end: date) -> tuple[str, list]:
    last: Exception | None = None
    for s in ALIASES.get(symbol, [symbol]):
        try:
            if interval == "1day":
                rows = _get("historical-price-eod/full", {"symbol": s, "from": start.isoformat(), "to": end.isoformat()})
            else:
                rows = _get("historical-chart/1hour", {"symbol": s, "from": start.isoformat(), "to": end.isoformat()})
            if rows:
                return s, rows
        except LookupError as exc:
            last = exc
    raise LookupError(str(last) if last else "no bars returned")


def run_fmp_bars(db: Session, src: Source):
    if not settings.fmp_api_key:
        raise SourceUnavailable("FMP_API_KEY not set (financialmodelingprep.com)")
    today = date.today()
    n, failed = 0, []
    for sym in SYMBOLS:
        # hourly: ~13 months on the first run (enough 4-hour candles for the 200 EMA + the 500-candle zone life)
        for interval, full_days, recent_days, chunk in (("1day", 5 * 365, 10, 5 * 365), ("1hour", 400, 4, 30)):
            have = db.scalar(select(func.count()).select_from(PriceBar).where(PriceBar.symbol == sym, PriceBar.interval == interval))
            start = today - timedelta(days=recent_days if have else full_days)
            try:
                while start <= today:
                    end = min(today, start + timedelta(days=chunk))
                    _time.sleep(0.25)  # stay well inside 300 requests a minute
                    _, rows = _fetch(sym, interval, start, end)
                    n += save_bars(db, sym, interval, rows)
                    start = end + timedelta(days=1)
                db.commit()
            except PermissionError as exc:
                raise SourceUnavailable(str(exc)) from exc
            except LookupError as exc:
                db.rollback()
                failed.append(f"{sym} {interval}: {exc}")
    if failed and n == 0:
        raise SourceUnavailable("; ".join(failed)[:900])
    return (n, ("Some symbols missing: " + "; ".join(failed))[:300]) if failed else n


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def bars(db: Session, symbol: str, interval: str, start: datetime | None = None, end: datetime | None = None) -> list:
    """Bars in time order, with times always in UTC (some databases hand them back without a time zone)."""
    q = select(PriceBar).where(PriceBar.symbol == symbol, PriceBar.interval == interval)
    if start is not None:
        q = q.where(PriceBar.ts >= start)
    if end is not None:
        q = q.where(PriceBar.ts <= end)
    from types import SimpleNamespace

    # read-only copies, so normalising the time never writes back to the database
    return [SimpleNamespace(symbol=b.symbol, interval=b.interval, ts=_utc(b.ts), open=b.open, high=b.high, low=b.low,
                            close=b.close, volume=b.volume) for b in db.scalars(q.order_by(PriceBar.ts))]


def atr_pct(db: Session, symbol: str, at: datetime, days: int = 14) -> float | None:
    """Average true range over the last `days` daily bars before `at`, as % of price."""
    rows = [b for b in bars(db, symbol, "1day", at - timedelta(days=days * 2 + 10), at) if b.ts + timedelta(days=1) <= at]
    rows = rows[-(days + 1):]
    if len(rows) < days // 2 + 1:
        return None
    trs = [max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close)) for p, b in zip(rows, rows[1:])]
    return round(sum(trs) / len(trs) / rows[-1].close * 100, 3) if trs and rows[-1].close else None
