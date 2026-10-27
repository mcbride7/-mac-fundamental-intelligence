"""Forex Factory weekly calendar feed: free, no key.

Fills the economic calendar with each event's time, impact, forecast (consensus) and previous value.
The feed has no actual values, so actuals still come from FRED, the central bank feeds and Data input.

The feed is a public file, not a supported API, and asks callers not to poll it often, so the
worker reads it every 6 hours. Only events the app tracks are kept, matched by an explicit table
of Forex Factory titles (safer than fuzzy matching: a wrong match would put the wrong forecast
next to an indicator)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy.orm import Session

from app.ingestion.base import SourceUnavailable
from app.models import EconomicEvent, Source
from app.services import data_access as da
from app.services.extraction.text_parser import parse_number

log = logging.getLogger(__name__)

FEEDS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",  # not always published; skipped if missing
]
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MacFundamentalIntelligence/1.0)"}

# (currency, Forex Factory title, lower-case) -> indicator code
TITLES: dict[tuple[str, str], str] = {}


def _add(ccy: str, code: str, *titles: str) -> None:
    for t in titles:
        TITLES[(ccy, t.lower())] = code


_add("USD", "US_CPI_YOY", "CPI y/y")
_add("USD", "US_CPI_MOM", "CPI m/m")
_add("USD", "US_CORE_CPI_YOY", "Core CPI y/y")
_add("USD", "US_PCE_YOY", "PCE Price Index y/y")
_add("USD", "US_CORE_PCE_YOY", "Core PCE Price Index y/y")
_add("USD", "US_PPI_YOY", "PPI y/y")
_add("USD", "US_NFP", "Non-Farm Employment Change")
_add("USD", "US_UNEMPLOYMENT", "Unemployment Rate")
_add("USD", "US_AHE_YOY", "Average Hourly Earnings y/y")
_add("USD", "US_GDP_QOQ", "Advance GDP q/q", "Prelim GDP q/q", "Final GDP q/q")
_add("USD", "US_RETAIL_SALES_MOM", "Retail Sales m/m")
_add("USD", "US_ISM_MANUF", "ISM Manufacturing PMI")
_add("USD", "US_ISM_SERVICES", "ISM Services PMI")
_add("USD", "US_FED_RATE", "Federal Funds Rate")
_add("USD", "US_JOBLESS_CLAIMS", "Unemployment Claims")
_add("USD", "US_JOLTS", "JOLTS Job Openings")
_add("USD", "US_ADP", "ADP Non-Farm Employment Change")

_add("EUR", "EA_HICP_YOY", "CPI Flash Estimate y/y", "Final CPI y/y", "CPI y/y")
_add("EUR", "EA_CORE_HICP_YOY", "Core CPI Flash Estimate y/y", "Final Core CPI y/y", "Core CPI y/y")
_add("EUR", "EA_UNEMPLOYMENT", "Unemployment Rate")
_add("EUR", "EA_GDP_QOQ", "Flash GDP q/q", "Prelim Flash GDP q/q", "Revised GDP q/q", "GDP q/q")
_add("EUR", "EA_ECB_RATE", "Deposit Facility Rate")

_add("GBP", "GB_CPI_YOY", "CPI y/y")
_add("GBP", "GB_CORE_CPI_YOY", "Core CPI y/y")
_add("GBP", "GB_UNEMPLOYMENT", "Unemployment Rate")
_add("GBP", "GB_GDP_QOQ", "Prelim GDP q/q", "Revised GDP q/q", "Final GDP q/q", "GDP q/q")
_add("GBP", "GB_BOE_RATE", "Official Bank Rate")

_add("JPY", "JP_CPI_YOY", "National CPI y/y")
_add("JPY", "JP_CORE_CPI_YOY", "National Core CPI y/y")
_add("JPY", "JP_BOJ_RATE", "BOJ Policy Rate")

_add("CHF", "CH_CPI_YOY", "CPI y/y")

_add("CAD", "CA_CPI_YOY", "CPI y/y")
_add("CAD", "CA_UNEMPLOYMENT", "Unemployment Rate")
_add("CAD", "CA_EMPLOYMENT_CHANGE", "Employment Change")

_add("AUD", "AU_CPI_YOY", "CPI y/y")
_add("AUD", "AU_UNEMPLOYMENT", "Unemployment Rate")

_add("NZD", "NZ_CPI_YOY", "CPI y/y")

_add("CNY", "CN_CPI_YOY", "CPI y/y")

_add("USD", "US_CB_CONF", "CB Consumer Confidence")
_add("USD", "US_UMICH", "Prelim UoM Consumer Sentiment", "Revised UoM Consumer Sentiment")
_add("EUR", "EA_RETAIL_SALES_MOM", "Retail Sales m/m")
_add("EUR", "EA_MANUF_PMI", "Flash Manufacturing PMI", "Final Manufacturing PMI")
_add("EUR", "EA_SERVICES_PMI", "Flash Services PMI", "Final Services PMI")
_add("EUR", "EA_CONSUMER_CONF", "Consumer Confidence")
_add("EUR", "EA_PPI_MOM", "PPI m/m")
_add("GBP", "GB_RETAIL_SALES_MOM", "Retail Sales m/m")
_add("GBP", "GB_MANUF_PMI", "Flash Manufacturing PMI", "Final Manufacturing PMI")
_add("GBP", "GB_SERVICES_PMI", "Flash Services PMI", "Final Services PMI")
_add("GBP", "GB_CLAIMANT", "Claimant Count Change")
_add("GBP", "GB_PPI_YOY", "PPI Input y/y")
_add("GBP", "GB_CONSUMER_CONF", "GfK Consumer Confidence")
_add("JPY", "JP_GDP_QOQ", "Prelim GDP q/q", "Final GDP q/q")
_add("JPY", "JP_RETAIL_SALES_YOY", "Retail Sales y/y")
_add("JPY", "JP_MANUF_PMI", "Flash Manufacturing PMI", "Final Manufacturing PMI")
_add("JPY", "JP_SERVICES_PMI", "Flash Services PMI", "Final Services PMI")
_add("JPY", "JP_UNEMPLOYMENT", "Unemployment Rate")
_add("JPY", "JP_PPI_YOY", "PPI y/y")
_add("CHF", "CH_GDP_QOQ", "GDP q/q")
_add("CHF", "CH_RETAIL_SALES_YOY", "Retail Sales y/y")
_add("CHF", "CH_MANUF_PMI", "Manufacturing PMI")
_add("CHF", "CH_UNEMPLOYMENT", "Unemployment Rate")
_add("CHF", "CH_PPI_MOM", "PPI m/m")
_add("CAD", "CA_GDP_MOM", "GDP m/m")
_add("CAD", "CA_RETAIL_SALES_MOM", "Retail Sales m/m")
_add("CAD", "CA_IVEY_PMI", "Ivey PMI")
_add("CAD", "CA_PPI_MOM", "IPPI m/m")
_add("AUD", "AU_GDP_QOQ", "GDP q/q")
_add("AUD", "AU_RETAIL_SALES_MOM", "Retail Sales m/m")
_add("AUD", "AU_EMPLOYMENT_CHANGE", "Employment Change")
_add("AUD", "AU_MANUF_PMI", "Flash Manufacturing PMI")
_add("AUD", "AU_SERVICES_PMI", "Flash Services PMI")
_add("AUD", "AU_PPI_QOQ", "PPI q/q")
_add("NZD", "NZ_GDP_QOQ", "GDP q/q")
_add("NZD", "NZ_UNEMPLOYMENT", "Unemployment Rate")
_add("NZD", "NZ_EMPLOYMENT_CHANGE", "Employment Change q/q")
_add("NZD", "NZ_RETAIL_SALES_QOQ", "Retail Sales q/q")

# business surveys (PMIs) and consumer confidence
_add("USD", "US_SPG_MANUF_PMI", "Flash Manufacturing PMI", "Final Manufacturing PMI")
_add("USD", "US_SPG_SERVICES_PMI", "Flash Services PMI", "Final Services PMI")
_add("AUD", "AU_MANUF_PMI", "Final Manufacturing PMI")
_add("AUD", "AU_SERVICES_PMI", "Final Services PMI")
_add("AUD", "AU_CONSUMER_CONF", "Westpac Consumer Sentiment")
_add("JPY", "JP_CONSUMER_CONF", "Consumer Confidence")
_add("CHF", "CH_SERVICES_PMI", "Services PMI", "procure.ch Services PMI")
_add("CHF", "CH_MANUF_PMI", "procure.ch Manufacturing PMI")
_add("CHF", "CH_CONSUMER_CONF", "SECO Consumer Climate")
_add("CAD", "CA_MANUF_PMI", "Manufacturing PMI", "S&P Global Manufacturing PMI")
_add("CAD", "CA_SERVICES_PMI", "Services PMI", "S&P Global Services PMI")
_add("NZD", "NZ_MANUF_PMI", "BusinessNZ Manufacturing Index")
_add("NZD", "NZ_SERVICES_PMI", "BusinessNZ Services Index")
_add("NZD", "NZ_CONSUMER_CONF", "ANZ-RM Consumer Confidence", "ANZ Consumer Confidence", "Westpac Consumer Sentiment")
_add("CNY", "CN_MANUF_PMI", "Manufacturing PMI")
_add("CNY", "CN_SERVICES_PMI", "Non-Manufacturing PMI")
_add("CNY", "CN_CAIXIN_MANUF_PMI", "Caixin Manufacturing PMI", "RatingDog Manufacturing PMI")
_add("CNY", "CN_CAIXIN_SERVICES_PMI", "Caixin Services PMI", "RatingDog Services PMI")

IMPORTANCE = {"high": "high", "medium": "medium", "low": "low"}


def parse_value(raw, unit: str | None) -> float | None:
    """'3.1%' -> 3.1, '250K' -> 250 (indicator in thousands), '1.2M' -> 1200, '<0.1%' -> 0.1, '' -> None."""
    if raw is None:
        return None
    s = str(raw).strip().replace("<", "").replace(">", "").replace("%", "").strip()
    if not s:
        return None
    mult = 1.0
    suffix = s[-1].upper()
    if suffix in "KMBT":
        s = s[:-1]
        if unit == "k":
            mult = {"K": 1, "M": 1_000, "B": 1_000_000, "T": 1_000_000_000}[suffix]
        elif unit == "m":
            mult = {"K": 0.001, "M": 1, "B": 1_000, "T": 1_000_000}[suffix]
        else:
            mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}[suffix]
    v = parse_number(s)
    return None if v is None else round(v * mult, 6)


def reference_period(frequency: str, released: datetime, title: str) -> str:
    """Which period a release describes, from its release date.
    meeting -> the meeting month; quarterly -> the last completed quarter;
    weekly -> the week-ending Saturday before the release (e.g. Thursday's jobless claims);
    monthly -> the previous month (a flash estimate late in the month describes that same month)."""
    d = released.date()
    if frequency == "meeting":
        return f"{d.year}-{d.month:02d}"
    if frequency == "weekly":
        back = (d.weekday() - 5) % 7 or 7
        return (d - timedelta(days=back)).isoformat()
    if frequency == "quarterly":
        q = (d.month - 1) // 3 + 1
        y, q = (d.year, q - 1) if q > 1 else (d.year - 1, 4)
        return f"{y}Q{q}"
    if "flash" in title.lower() and d.day >= 25:
        return f"{d.year}-{d.month:02d}"
    prev = d.replace(day=1) - timedelta(days=1)
    return f"{prev.year}-{prev.month:02d}"


def fetch() -> list[dict]:
    items: list[dict] = []
    for i, url in enumerate(FEEDS):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException as exc:
            if i == 0:
                raise SourceUnavailable(f"Could not reach Forex Factory: {exc.__class__.__name__}") from exc
            continue
        if r.status_code != 200:
            if i == 0:
                hint = " (asked too often: it allows a few requests per hour)" if r.status_code == 429 else ""
                raise SourceUnavailable(f"Forex Factory feed returned {r.status_code}{hint}")
            continue
        try:
            data = r.json()
        except ValueError as exc:
            if i == 0:
                raise SourceUnavailable("Forex Factory sent something that isn't the calendar (not JSON)") from exc
            continue
        if isinstance(data, list):
            items.extend(x for x in data if isinstance(x, dict))
    return items


def store(db: Session, items: list[dict]) -> tuple[int, int]:
    """Upsert tracked events. Returns (events written, items seen)."""
    n = 0
    for item in items:
        ccy = (item.get("country") or "").upper()
        title = (item.get("title") or "").strip()
        code = TITLES.get((ccy, title.lower()))
        if not code:
            continue
        ind = da.indicator_by_code(db, code)
        if ind is None:
            continue
        try:
            when = datetime.fromisoformat(item["date"]).astimezone(timezone.utc)
        except (KeyError, TypeError, ValueError):
            continue
        period = reference_period(ind.frequency, when, title)
        ev = da.event_for(db, ind.id, period)
        if ev is None:
            ev = EconomicEvent(indicator_id=ind.id, reference_period=period, importance=ind.importance)
            db.add(ev)
            db.flush()
        ev.scheduled_at = when
        imp = IMPORTANCE.get((item.get("impact") or "").lower())
        if imp:
            ev.importance = imp
        forecast = parse_value(item.get("forecast"), ind.unit)
        previous = parse_value(item.get("previous"), ind.unit)
        # a forecast you typed in yourself wins over the feed
        if forecast is not None and ev.consensus_source != "manual":
            ev.consensus, ev.consensus_source = forecast, "forexfactory"
        if previous is not None:
            ev.previous = previous
        n += 1
    db.commit()
    return n, len(items)


def run_forexfactory(db: Session, src: Source) -> int:
    items = fetch()
    if not items:
        raise SourceUnavailable("Forex Factory feed was empty")
    n, seen = store(db, items)
    log.info("Forex Factory: %s tracked events updated out of %s in the feed", n, seen)
    return n

