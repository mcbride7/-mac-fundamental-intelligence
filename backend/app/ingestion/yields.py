"""Free daily government bond yields outside the US, for market-based rate pricing.

  EUR  ECB Data Portal, euro area AAA government yield curve (spot rates), 2-year and 10-year.
       Stored as country "DE" (the app's euro yield country); the AAA curve tracks German Bunds closely.
  GBP  Bank of England database, nominal gilt par yields: 5-year (IUDSNPY) and 10-year (IUDMNPY).
       The Bank's database has no 2-year gilt series, so the 5-year is used for GBP rate pricing.

With no rate odds typed in, the app reads "short yield minus policy rate" as the market's expected
change (shown as "proxy"). Both services are free and need no key.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.ingestion.base import SourceUnavailable, http_get
from app.models import BondYield, Source

ECB_URL = "https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.{tenor}"
ECB_SERIES = {"2Y": "SR_2Y", "10Y": "SR_10Y"}
BOE_URL = "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp"
BOE_SERIES = {"5Y": "IUDSNPY", "10Y": "IUDMNPY"}
LOOKBACK_DAYS = 400


def parse_ecb_csv(text: str) -> list[tuple[date, float]]:
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        d, v = r.get("TIME_PERIOD"), r.get("OBS_VALUE")
        if not d or v in (None, "", "NaN"):
            continue
        try:
            out.append((date.fromisoformat(d[:10]), float(v)))
        except ValueError:
            continue
    return out


def parse_boe_csv(text: str, code: str) -> list[tuple[date, float]]:
    """Bank of England CSV: DATE,<code> with dates like '27 Oct 2026'. An HTML page means an error."""
    if text.lstrip().startswith("<"):
        raise SourceUnavailable("Bank of England database returned a web page instead of data")
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        d, v = (r.get("DATE") or "").strip(), (r.get(code) or "").strip()
        if not d or not v:
            continue
        try:
            out.append((datetime.strptime(d, "%d %b %Y").date(), float(v)))
        except ValueError:
            continue
    return out


def fetch_ecb(tenor: str) -> list[tuple[date, float]]:
    start = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    r = http_get(ECB_URL.format(tenor=ECB_SERIES[tenor]), {"startPeriod": start, "format": "csvdata"}, retries=1)
    return parse_ecb_csv(r.text)


def fetch_boe(tenor: str) -> list[tuple[date, float]]:
    code = BOE_SERIES[tenor]
    start = (date.today() - timedelta(days=LOOKBACK_DAYS)).strftime("%d/%b/%Y")
    r = http_get(BOE_URL, {"csv.x": "yes", "SeriesCodes": code, "UsingCodes": "Y", "CSVF": "TN",
                           "Datefrom": start, "Dateto": "now"}, retries=1)
    return parse_boe_csv(r.text, code)


def store(db: Session, country: str, tenor: str, rows: list[tuple[date, float]], source: str) -> int:
    n = 0
    for d, v in rows:
        ts = datetime.combine(d, time(17, 0), tzinfo=timezone.utc)
        if db.get(BondYield, (country, tenor, ts)) is None:
            db.add(BondYield(country=country, tenor=tenor, ts=ts, yield_pct=v, source=source))
            n += 1
    return n


def run_yields(db: Session, src: Source) -> int:
    n, errors, ok = 0, [], 0
    jobs = [("DE", t, lambda t=t: fetch_ecb(t), "ECB AAA curve") for t in ECB_SERIES] + \
           [("GB", t, lambda t=t: fetch_boe(t), "Bank of England") for t in BOE_SERIES]
    for country, tenor, fetch, label in jobs:
        try:
            rows = fetch()
            if not rows:
                raise SourceUnavailable("no data returned")
            n += store(db, country, tenor, rows, label)
            db.commit()
            ok += 1
        except Exception as exc:  # one failing series doesn't stop the others
            db.rollback()
            errors.append(f"{label} {tenor}: {exc}"[:200])
    if not ok:
        raise SourceUnavailable("; ".join(errors))
    return n
