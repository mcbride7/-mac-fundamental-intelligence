"""Market data (Twelve Data) and economic calendar (Finnhub) connectors."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.base import SourceUnavailable, http_get
from app.models import EconomicEvent, MarketPrice, Source
from app.services import data_access as da
from app.services.extraction.normalizer import map_indicator
from app.services.extraction.text_parser import detect_period

# internal symbol -> (provider symbol, asset class)
SYMBOLS = {
    "EURUSD": ("EUR/USD", "fx"), "GBPUSD": ("GBP/USD", "fx"), "USDJPY": ("USD/JPY", "fx"),
    "USDCHF": ("USD/CHF", "fx"), "AUDUSD": ("AUD/USD", "fx"), "NZDUSD": ("NZD/USD", "fx"),
    "USDCAD": ("USD/CAD", "fx"), "USDZAR": ("USD/ZAR", "fx"), "USDMXN": ("USD/MXN", "fx"),
    "USDCNY": ("USD/CNY", "fx"), "XAUUSD": ("XAU/USD", "commodity"), "XAGUSD": ("XAG/USD", "commodity"),
    "WTI": ("WTI/USD", "commodity"), "BTCUSD": ("BTC/USD", "crypto"), "SPX": ("SPX", "equity"),
}


def run_prices(db: Session, src: Source) -> int:
    if not settings.twelvedata_api_key:
        raise SourceUnavailable("TWELVEDATA_API_KEY not set")
    n = 0
    for sym, (provider_sym, cls) in SYMBOLS.items():
        r = http_get("https://api.twelvedata.com/time_series",
                     {"symbol": provider_sym, "interval": "5min", "outputsize": 300,
                      "apikey": settings.twelvedata_api_key, "timezone": "UTC"})
        data = r.json()
        if data.get("status") == "error":
            continue
        for v in data.get("values", []):
            ts = datetime.fromisoformat(v["datetime"]).replace(tzinfo=timezone.utc)
            if db.get(MarketPrice, (sym, ts)) is None:
                db.add(MarketPrice(symbol=sym, ts=ts, price=float(v["close"]), asset_class=cls, source="twelvedata"))
                n += 1
        db.commit()
    return n


FINNHUB_COUNTRY = {"US": "US", "EU": "EA", "EMU": "EA", "GB": "GB", "UK": "GB", "JP": "JP", "CH": "CH",
                   "CA": "CA", "AU": "AU", "NZ": "NZ", "ZA": "ZA", "CN": "CN", "MX": "MX"}


def run_finnhub(db: Session, src: Source) -> int:
    from app.ingestion.fred import upsert_official_release

    if not settings.finnhub_api_key:
        raise SourceUnavailable("FINNHUB_API_KEY not set")
    today = date.today()
    r = http_get("https://finnhub.io/api/v1/calendar/economic",
                 {"from": (today - timedelta(days=7)).isoformat(), "to": (today + timedelta(days=21)).isoformat(),
                  "token": settings.finnhub_api_key})
    refs = da.indicator_refs(db)
    n = 0
    for item in r.json().get("economicCalendar", []):
        country = FINNHUB_COUNTRY.get((item.get("country") or "").upper())
        if not country:
            continue
        code, conf, _ = map_indicator(item.get("event", ""), country, None, refs)
        if not code or conf < 70:
            continue
        ind = da.indicator_by_code(db, code)
        when = datetime.fromisoformat(item["time"].replace(" ", "T")).replace(tzinfo=timezone.utc) \
            if item.get("time") else None
        period, _ = detect_period(item.get("event", ""))
        if not period and when:
            # releases describe the previous month/quarter by default
            ref = (when.replace(day=1) - timedelta(days=1))
            period = f"{ref.year}Q{(ref.month - 1) // 3 + 1}" if ind.frequency == "quarterly" \
                else f"{ref.year}-{ref.month:02d}"
        if not period:
            continue
        ev = da.event_for(db, ind.id, period)
        if ev is None:
            ev = EconomicEvent(indicator_id=ind.id, reference_period=period, importance=ind.importance)
            db.add(ev)
            db.flush()
        ev.scheduled_at = when or ev.scheduled_at
        if item.get("estimate") is not None:
            ev.consensus, ev.consensus_source = float(item["estimate"]), "finnhub"
        if item.get("prev") is not None:
            ev.previous = float(item["prev"])
        if item.get("actual") is not None:
            n += upsert_official_release(db, src, ind, period, float(item["actual"]), ev.consensus, when)
        n += 1
    db.commit()
    return n


def latest_price(db: Session, symbol: str) -> MarketPrice | None:
    return db.scalar(select(MarketPrice).where(MarketPrice.symbol == symbol).order_by(MarketPrice.ts.desc()))


def price_at(db: Session, symbol: str, ts: datetime, before: bool = True) -> MarketPrice | None:
    q = select(MarketPrice).where(MarketPrice.symbol == symbol)
    q = q.where(MarketPrice.ts <= ts).order_by(MarketPrice.ts.desc()) if before else \
        q.where(MarketPrice.ts >= ts).order_by(MarketPrice.ts)
    return db.scalar(q)


def currency_pair_for(ccy: str) -> tuple[str, int] | None:
    """Symbol that prices `ccy` against USD and the sign (+1 if ccy is the base)."""
    for sym in SYMBOLS:
        if len(sym) == 6 and sym.startswith(ccy) and sym.endswith("USD"):
            return sym, +1
        if len(sym) == 6 and sym.startswith("USD") and sym.endswith(ccy):
            return sym, -1
    return None

