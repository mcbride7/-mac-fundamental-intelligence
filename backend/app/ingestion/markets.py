"""Market data (Twelve Data) and economic calendar (Finnhub) connectors."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.base import SourceUnavailable, http_get
from app.models import EconomicEvent, Indicator, MarketPrice, Source
from app.services import data_access as da
from app.services.extraction.normalizer import map_indicator
from app.services.extraction.text_parser import detect_period, detect_transform

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
    import os
    import time

    import requests

    # Free plan: about 8 requests a minute. Pace the calls (set TWELVEDATA_DELAY=0 on a paid plan).
    delay = float(os.getenv("TWELVEDATA_DELAY", "8"))
    n, ok, skipped = 0, 0, []
    for i, (sym, (provider_sym, cls)) in enumerate(SYMBOLS.items()):
        if i and delay:
            time.sleep(delay)
        # Some symbols (indices, some commodities) need a paid plan and come back as 403.
        # Skip those one by one instead of failing the whole run.
        try:
            r = requests.get("https://api.twelvedata.com/time_series",
                             params={"symbol": provider_sym, "interval": "5min", "outputsize": 300,
                                     "apikey": settings.twelvedata_api_key, "timezone": "UTC"},
                             timeout=30)
            data = r.json()
        except (requests.RequestException, ValueError) as exc:
            skipped.append(f"{sym}: {exc.__class__.__name__}")
            continue
        if r.status_code >= 400 or data.get("status") == "error":
            skipped.append(f"{sym}: {data.get('code', r.status_code)} {data.get('message', '')}".strip())
            continue
        ok += 1
        for v in data.get("values", []):
            ts = datetime.fromisoformat(v["datetime"]).replace(tzinfo=timezone.utc)
            if db.get(MarketPrice, (sym, ts)) is None:
                db.add(MarketPrice(symbol=sym, ts=ts, price=float(v["close"]), asset_class=cls, source="twelvedata"))
                n += 1
        db.commit()
    if not ok:
        raise SourceUnavailable("Twelve Data refused every symbol. Check TWELVEDATA_API_KEY on api and worker. "
                                "First reply: " + (skipped[0] if skipped else "none"))
    if skipped:
        import logging

        logging.getLogger(__name__).info("Twelve Data skipped (not on your plan): %s", "; ".join(skipped))
    return n


FINNHUB_COUNTRY = {"US": "US", "EU": "EA", "EMU": "EA", "GB": "GB", "UK": "GB", "JP": "JP", "CH": "CH",
                   "CA": "CA", "AU": "AU", "NZ": "NZ", "ZA": "ZA", "CN": "CN", "MX": "MX"}


# FMP's own names for releases whose site name is worded differently (period tag "(Oct)" left off)
FMP_ALIASES = {
    "US_UMICH": ["michigan consumer sentiment"],
    "US_ISM_SERVICES": ["ism services pmi", "ism non-manufacturing pmi"],
    "EA_MANUF_PMI": ["s&p global manufacturing pmi", "hcob manufacturing pmi"],
    "EA_SERVICES_PMI": ["s&p global services pmi", "hcob services pmi"],
    "EA_PMI_COMPOSITE": ["s&p global composite pmi", "hcob composite pmi"],
    "GB_MANUF_PMI": ["s&p global manufacturing pmi"], "GB_SERVICES_PMI": ["s&p global services pmi"],
    "GB_CONSUMER_CONF": ["gfk consumer confidence", "consumer confidence"],
    "CH_CONSUMER_CONF": ["consumer confidence"],  # SECO's monthly reading (the "(Q4)" one is quarterly)
    "JP_MANUF_PMI": ["s&p global manufacturing pmi", "jibun bank manufacturing pmi"],
    "JP_SERVICES_PMI": ["s&p global services pmi", "jibun bank services pmi"],
    "AU_MANUF_PMI": ["s&p global manufacturing pmi"], "AU_SERVICES_PMI": ["s&p global services pmi"],
    "AU_CONSUMER_CONF": ["westpac consumer confidence index", "westpac consumer confidence"],
    "AU_CORE_TRIMMED_MEAN_YOY": ["rba trimmed mean cpi"],
    "CA_MANUF_PMI": ["s&p global manufacturing pmi"], "CA_SERVICES_PMI": ["s&p global services pmi"],
    "CH_MANUF_PMI": ["procure.ch manufacturing pmi"], "CH_SERVICES_PMI": ["procure.ch services pmi"],
    "NZ_MANUF_PMI": ["business nz pmi", "businessnz pmi"], "NZ_SERVICES_PMI": ["services nz psi", "businessnz psi"],
    "NZ_CONSUMER_CONF": ["anz roy morgan consumer confidence"],
    "CN_CAIXIN_MANUF_PMI": ["s&p global manufacturing pmi", "ratingdog manufacturing pmi"],
    "CN_CAIXIN_SERVICES_PMI": ["s&p global services pmi", "ratingdog services pmi"],
    "MX_MANUF_PMI": ["s&p global manufacturing pmi"],
    "ZA_SERVICES_PMI": ["s&p global composite pmi"],
    "ZA_SARB_RATE": ["interest rate decision"],
    "GB_UNEMPLOYMENT": ["ilo unemployment rate"],
}
_MONTHS = r"jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"


def fmp_refs(refs: list) -> list:
    """The site's indicators with FMP's extra names added."""
    from dataclasses import replace as _replace

    return [_replace(r, aliases=list(r.aliases or []) + FMP_ALIASES.get(r.code, [])) for r in refs]


def fmp_match(item: dict, country: str, refs: list, freq: dict) -> str | None:
    """The indicator an FMP calendar line fills, or None. Strict: FMP lists every sub-measure next to the
    headline ("ISM Manufacturing Prices", "U-6 Unemployment Rate", "CPI s.a" index level, "GDP Capital
    Expenditure QoQ"), so only an exact name counts, an index level never fills a %-change indicator, and a
    quarterly print never fills a monthly indicator (or the reverse)."""
    import re as _re

    name = item.get("event") or ""
    tr = detect_transform(name)
    code, conf, _ = map_indicator(name, country, tr, refs, exact=True)
    if not code or conf < 70:
        return None
    ref = next((r for r in refs if r.code == code), None)
    low = name.lower()
    if code == "JP_CORE_CPI_YOY" and "tokyo" in low:
        return None  # the national figure; Tokyo's early read stays on the calendar only
    if ref is not None:
        names = " ".join([ref.name] + list(ref.aliases or [])).lower()
        for word in ("change", "annualized", "annualised"):
            if word in low and word not in names and not (word.startswith("annuali") and ref.transform == "qoq_saar"):
                return None  # "Westpac Consumer Confidence Change" is not the index; "GDP Annualized" not q/q
    unit = str(item.get("unit") or "").strip().lower()
    if ref is not None and (ref.transform or "") in ("yoy", "mom", "qoq", "qoq_saar"):
        if unit == "index" or (not tr and unit != "%"):
            return None  # "CPI (Oct)" 337.5 index level, "Producer Price Index (Oct)" 160.3
    tag = _re.search(r"\((q[1-4]|" + _MONTHS + r")[a-z]*\)", name.lower())
    f = freq.get(code)
    if tag and f:
        quarterly_tag = tag.group(1).startswith("q")
        if (f == "quarterly") != quarterly_tag and f in ("monthly", "quarterly"):
            return None  # Australia's quarterly CPI vs the monthly one; UK monthly GDP vs quarterly GDP
    return code


def period_tag(name: str) -> str | None:
    """The period a provider tags on a release name: "(Sep)" -> "sep", "(Q3)" -> "q3"."""
    import re as _re

    m = _re.search(r"\((q[1-4]|" + _MONTHS + r")[a-z]*\)", (name or "").lower())
    return m.group(1) if m else None


def _tag_of_period(period: str) -> str | None:
    """"2026-08" -> "aug", "2026Q3" -> "q3"."""
    if "Q" in period:
        return "q" + period[-1]
    try:
        return _MONTHS.split("|")[int(period[5:7]) - 1]
    except (ValueError, IndexError):
        return None


def tagged_period(frequency: str | None, when: datetime | None, name: str) -> str | None:
    """The period the provider printed on the release, "(Oct)" -> "2026-10", "(Q3)" -> "2026Q3", with the year
    from the release date (an "(Dec)" print in January is last year's). None when there is no tag or the
    indicator is weekly / per meeting."""
    tag = period_tag(name)
    if not tag or when is None or frequency not in ("monthly", "quarterly"):
        return None
    y, m = when.year, when.month
    if tag.startswith("q"):
        if frequency != "quarterly":
            return None
        q = int(tag[1])
        return f"{y if (q - 1) * 3 + 1 <= m else y - 1}Q{q}"
    if frequency != "monthly":
        return None
    mon = _MONTHS.split("|").index(tag) + 1
    return f"{y if mon <= m else y - 1}-{mon:02d}"


def _release_count(db: Session, event_id: int) -> int:
    from sqlalchemy import func

    from app.models.core import EconomicRelease

    return db.scalar(select(func.count()).select_from(EconomicRelease).where(EconomicRelease.event_id == event_id)) or 0


def fmp_event(db: Session, ind, when: datetime | None, name: str) -> EconomicEvent | None:
    """The calendar event an FMP print fills, filed under the period FMP printed: "Consumer Confidence (Oct)"
    released 29 October is October, not September as the release-date rule guesses. An event that the
    calendar filed under a wrong period is corrected (when nothing is stored on it yet)."""
    ev = calendar_event(db, ind, when, name)
    want = tagged_period(ind.frequency, when, name)
    if ind.frequency == "weekly" and ev is not None and when is not None:
        import re as _re

        from app.ingestion.forexfactory import reference_period

        if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", ev.reference_period or ""):
            want = reference_period("weekly", when, name)  # weekly figures are filed by week, not "2026-10"
    if ev is None or not want or ev.reference_period == want:
        return ev
    right = da.event_for(db, ind.id, want)
    if right is not None:
        if right.scheduled_at is None or ev.scheduled_at == right.scheduled_at:
            right.scheduled_at = ev.scheduled_at
        return right
    if _release_count(db, ev.id) == 0:
        ev.reference_period = want
        db.flush()
        return ev
    right = EconomicEvent(indicator_id=ind.id, reference_period=want, importance=ev.importance,
                          scheduled_at=when or ev.scheduled_at)
    db.add(right)
    db.flush()
    return right


def calendar_event(db: Session, ind, when: datetime | None, name: str) -> EconomicEvent | None:
    """The calendar event a provider's release belongs to. First the event already on the calendar for this
    indicator at (about) the same release time, whatever period it was filed under; otherwise the period by
    Forex Factory's rules, so every source fills the same event the calendar shows."""
    from app.ingestion.forexfactory import reference_period

    if when is not None:
        near = db.scalars(select(EconomicEvent).where(
            EconomicEvent.indicator_id == ind.id, EconomicEvent.scheduled_at >= when - timedelta(hours=18),
            EconomicEvent.scheduled_at <= when + timedelta(hours=18))).all()
        if near:
            def gap(e):
                t = e.scheduled_at if e.scheduled_at.tzinfo else e.scheduled_at.replace(tzinfo=timezone.utc)
                return abs((t - when).total_seconds())
            return min(near, key=gap)
        period = reference_period(ind.frequency, when, name)
    else:
        period, _ = detect_period(name)
        if not period:
            return None
    ev = da.event_for(db, ind.id, period)
    if ev is None:
        ev = EconomicEvent(indicator_id=ind.id, reference_period=period, importance=ind.importance)
        db.add(ev)
        db.flush()
    return ev


def run_finnhub(db: Session, src: Source) -> int:
    from app.ingestion.fred import upsert_official_release

    if settings.fmp_api_key:
        logging.getLogger(__name__).info("Finnhub calendar: not needed, FMP is the economic calendar")
        return 0
    if not settings.finnhub_api_key:
        raise SourceUnavailable("FINNHUB_API_KEY not set")
    today = date.today()
    try:
        r = http_get("https://finnhub.io/api/v1/calendar/economic",
                     {"from": (today - timedelta(days=7)).isoformat(), "to": (today + timedelta(days=21)).isoformat(),
                      "token": settings.finnhub_api_key})
    except SourceUnavailable as exc:
        if "403" in str(exc):
            raise SourceUnavailable("Finnhub's economic calendar needs a paid Finnhub plan (403). Add calendar "
                                    "data with a screenshot or pasted table in Data input instead.") from exc
        raise
    refs = da.indicator_refs(db)
    n = 0
    for item in r.json().get("economicCalendar", []):
        country = FINNHUB_COUNTRY.get((item.get("country") or "").upper())
        if not country:
            continue
        code, conf, _ = map_indicator(item.get("event", ""), country, detect_transform(item.get("event", "")), refs)
        if not code or conf < 70:
            continue
        ind = da.indicator_by_code(db, code)
        when = datetime.fromisoformat(item["time"].replace(" ", "T")).replace(tzinfo=timezone.utc) \
            if item.get("time") else None
        ev = calendar_event(db, ind, when, item.get("event", ""))
        if ev is None:
            continue
        period = ev.reference_period
        # backup to FMP: fill only what's missing; never replace FMP's or a typed-in forecast
        if ev.scheduled_at is None and when:
            ev.scheduled_at = when
        if item.get("estimate") is not None and ev.consensus_source not in ("manual", "fmp"):
            ev.consensus, ev.consensus_source = float(item["estimate"]), "finnhub"
        if item.get("prev") is not None and ev.previous is None:
            ev.previous = float(item["prev"])
        if item.get("actual") is not None:
            n += upsert_official_release(db, src, ind, period, float(item["actual"]), ev.consensus, when)
        n += 1
    db.commit()
    return n


FMP_URLS = ("https://financialmodelingprep.com/stable/economic-calendar",
            "https://financialmodelingprep.com/api/v3/economic_calendar")


def _fmp_get(params: dict) -> list:
    """FMP's calendar (current 'stable' address, then the older v3 one). Explains plan / key problems plainly."""
    import requests

    last = ""
    for url in FMP_URLS:
        try:
            r = requests.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            last = f"{exc.__class__.__name__}"
            continue
        try:
            body = r.json()
        except ValueError:
            body = None
        msg = body.get("Error Message") or body.get("message") if isinstance(body, dict) else None
        if r.status_code in (401,) or (msg and "invalid" in msg.lower() and "key" in msg.lower()):
            raise SourceUnavailable("FMP rejected the API key: check FMP_API_KEY in Railway")
        if r.status_code in (402, 403) or (msg and ("subscription" in msg.lower() or "premium" in msg.lower()
                                                     or "restricted" in msg.lower())):
            last = "FMP's free plan doesn't include the economic calendar (needs a paid FMP plan)"
            continue
        if r.status_code == 429 or (msg and "limit" in msg.lower()):
            raise SourceUnavailable("FMP daily request limit reached (free plan: 250 a day); it will retry later")
        if r.status_code >= 400 or not isinstance(body, list):
            last = f"FMP returned {r.status_code}: {(msg or r.text[:120]).strip()}"
            continue
        return body
    raise SourceUnavailable(last or "FMP calendar unreachable")


def run_fmp(db: Session, src: Source) -> int:
    """Main calendar source: release times, forecasts, previous figures and actuals. Forex Factory and Finnhub
    fill only what FMP doesn't have; a forecast typed in by hand is never overwritten."""
    from app.ingestion.fred import upsert_official_release

    if not settings.fmp_api_key:
        raise SourceUnavailable("FMP_API_KEY not set (free key from financialmodelingprep.com)")
    today = date.today()
    start = today - timedelta(days=FMP_LOOKBACK_DAYS)
    rows = _fmp_get({"from": start.isoformat(), "to": (today + timedelta(days=21)).isoformat(),
                     "apikey": settings.fmp_api_key})
    refs = fmp_refs(da.indicator_refs(db))
    freq = dict(db.execute(select(Indicator.code, Indicator.frequency)).all())
    n = 0
    filled: set[int] = set()  # events already filled this run: FMP repeats a release under two names
    written: set[tuple[int, str]] = set()
    matched: dict[tuple[str, str], list[dict]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        country = FINNHUB_COUNTRY.get((item.get("country") or "").upper())
        if not country:
            continue
        code = fmp_match(item, country, refs, freq)
        if code:
            matched.setdefault((code, str(item.get("date"))), []).append(item)
    for (code, _), group in matched.items():
        item = next((g for g in group if g.get("actual") is not None), group[0])
        name = item.get("event") or ""
        ind = da.indicator_by_code(db, code)
        if ind is None:
            continue
        try:
            when = datetime.fromisoformat(str(item.get("date")).replace(" ", "T")[:19]).replace(tzinfo=timezone.utc)
        except ValueError:
            when = None
        ev = fmp_event(db, ind, when, name)
        if ev is None or ev.id in filled:
            continue
        filled.add(ev.id)
        period = ev.reference_period
        if len(group) > 1:
            # one release, two prints (Canada's GDP: the month just gone and a flash for the next):
            # the one for the period the calendar event is filed under
            want = _tag_of_period(period)
            item = next((g for g in group if period_tag(g.get("event") or "") == want), item)
        # FMP is the main calendar: its time, forecast and previous figure replace Forex Factory's
        # (a forecast you typed in yourself still wins)
        if when:
            ev.scheduled_at = when
        imp = {"high": "high", "medium": "medium", "low": "low"}.get(str(item.get("impact") or "").lower())
        if imp:
            ev.importance = imp
        if item.get("estimate") is not None and ev.consensus_source != "manual":
            ev.consensus, ev.consensus_source = float(item["estimate"]), "fmp"
        if item.get("previous") is not None:
            ev.previous = float(item["previous"])
        if item.get("actual") is not None:
            n += upsert_official_release(db, src, ind, period, float(item["actual"]), ev.consensus, when)
            written.add((ind.id, period))
        n += 1
    db.flush()
    # typed-in numbers filed under the month they were typed in: placed once FMP's events (with their
    # release dates) are on the calendar, so each goes to the period that was really out at the time
    from app.services.macro_edit import fix_too_new_periods

    n += fix_too_new_periods(db)
    # only where FMP's reply really covers the dates (a short or cut-off reply never removes anything)
    seen = sorted(str(i.get("date"))[:10] for i in rows if isinstance(i, dict) and i.get("date"))
    if len(rows) >= 100 and seen and seen[0] <= (start + timedelta(days=2)).isoformat():
        since = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
        n += _drop_bad_fmp(db, src, since, written, filled)
    db.commit()
    return n


FMP_LOOKBACK_DAYS = 35


def _drop_bad_fmp(db: Session, src: Source, since: datetime, written: set, filled: set) -> int:
    """Remove FMP figures from the lookback window that today's strict matching no longer gives: the old,
    looser matching filed sub-measures under headline indicators ("ISM Manufacturing Prices" as the ISM
    PMI, Michigan inflation expectations as US CPI). Where FMP had overwritten another source's figure,
    that figure becomes current again."""
    from app.models.core import EconomicRelease

    bad = db.scalars(select(EconomicRelease).where(
        EconomicRelease.source_id == src.id, EconomicRelease.released_at >= since)).all()
    keys = {(r.indicator_id, r.reference_period) for r in bad} - written
    dropped = 0
    for ind_id, period in keys:
        rows = db.scalars(select(EconomicRelease).where(
            EconomicRelease.indicator_id == ind_id, EconomicRelease.reference_period == period)
            .order_by(EconomicRelease.id)).all()
        mine = [r for r in rows if r.source_id == src.id]
        others = [r for r in rows if r.source_id != src.id]
        if not mine:
            continue
        db.flush()
        for r in mine:
            _drop_release(db, r.id)
        dropped += len(mine)
        if others and not any(r.is_current for r in others):
            last = others[-1]
            last.is_current, last.verification_status = True, "VERIFIED"
        ev = da.event_for(db, ind_id, period)
        if ev is not None and not others and ev.id not in filled and ev.consensus_source in (None, "fmp"):
            if _event_unused(db, ev.id):
                db.delete(ev)
    if dropped:
        db.flush()
    return dropped


def _refs_to(table: str) -> list:
    """(table, column) pairs that point at `table`'s id, from the metadata, so a new link is never missed."""
    import app.models  # noqa: F401  (every model registered)
    from app.db import Base

    out = []
    for t in Base.metadata.sorted_tables:
        for c in t.columns:
            if any(f.column.table.name == table for f in c.foreign_keys):
                out.append((t, c))
    return out


def _drop_release(db: Session, release_id: int) -> None:
    """Delete a release: links that may be empty are cleared, rows computed from it (surprises, forecast
    errors) go with it."""
    from sqlalchemy import delete, update

    from app.models.core import EconomicRelease

    for t, c in _refs_to("economic_releases"):
        if c.nullable:
            db.execute(update(t).where(c == release_id).values({c.name: None}))
        elif t.name != "economic_releases":
            db.execute(delete(t).where(c == release_id))
    db.execute(delete(EconomicRelease).where(EconomicRelease.id == release_id))


def _event_unused(db: Session, event_id: int) -> bool:
    for t, c in _refs_to("economic_events"):
        if db.execute(select(c).select_from(t).where(c == event_id).limit(1)).first():
            return False
    return True


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

