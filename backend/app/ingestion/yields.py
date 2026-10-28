"""Free daily government bond yields outside the US, for market-based rate pricing.

  EUR  ECB Data Portal, euro area AAA government yield curve (spot rates), 2-year and 10-year.
       Stored as country "DE" (the app's euro yield country); the AAA curve tracks German Bunds closely.
  GBP  Bank of England database, nominal gilt par yields: 5-year (IUDSNPY) and 10-year (IUDMNPY).
       The Bank's database has no 2-year gilt series, so the 5-year is used for GBP rate pricing.
  CAD  Bank of Canada Valet service: 2-year and 10-year Government of Canada benchmark bond yields.
  AUD  Reserve Bank of Australia table F2 (CSV): 2-year and 10-year Australian Government bond yields.
  JPY  Japan Ministry of Finance JGB interest rate CSV: 2-year and 10-year.
  CHF  Swiss National Bank data portal, cube rendoblid: 2-year and 10-year Confederation bond spot rates.
  (NZD: the Reserve Bank of New Zealand blocks automated downloads, so NZD still relies on typed-in odds.)

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


BOC_URL = "https://www.bankofcanada.ca/valet/observations/{series}/json"
BOC_SERIES = {"2Y": "BD.CDN.2YR.DQ.YLD", "10Y": "BD.CDN.10YR.DQ.YLD"}
RBA_URL = "https://www.rba.gov.au/statistics/tables/csv/f2-data.csv"
RBA_SERIES = {"2Y": ("FCMYGBAG2D", "2 year"), "10Y": ("FCMYGBAG10D", "10 year")}
MOF_URLS = ["https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv",
            "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv"]
SNB_URL = "https://data.snb.ch/api/cube/rendoblid/data/csv/en"
SNB_SERIES = {"2Y": "2J", "10Y": "10J"}
DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%Y-%m")


def _date(text: str) -> date | None:
    t = text.strip().strip('"')
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(t, f).date()
        except ValueError:
            continue
    return None


def _num(text: str) -> float | None:
    t = (text or "").strip().strip('"').replace(",", "")
    if t in ("", "-", "NaN", "ND", "n/a", "*"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_boc_json(data: dict, series: str) -> list[tuple[date, float]]:
    out = []
    for o in data.get("observations", []):
        d, v = _date(o.get("d", "")), _num(str((o.get(series) or {}).get("v", "")))
        if d and v is not None:
            out.append((d, v))
    return out


def parse_rba_csv(text: str, series_id: str, title_hint: str) -> list[tuple[date, float]]:
    """RBA statistical table CSV: several header rows (Title, Description, ..., Series ID), then date rows."""
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    col = None
    for r in rows[:15]:
        if r and r[0].strip().lower() == "series id":
            col = next((i for i, c in enumerate(r) if c.strip().upper() == series_id), None)
    if col is None:  # fall back to the title row
        for r in rows[:15]:
            if r and r[0].strip().lower() == "title":
                col = next((i for i, c in enumerate(r) if title_hint in c.lower() and "government" in c.lower()), None)
    if col is None:
        raise SourceUnavailable(f"RBA table F2: column {series_id} not found")
    out = []
    for r in rows:
        if len(r) > col and r[0] and (d := _date(r[0])) and (v := _num(r[col])) is not None:
            out.append((d, v))
    return out


def parse_mof_csv(text: str, tenor: str) -> list[tuple[date, float]]:
    """MOF JGB CSV: a title line, then a header 'Date,1Y,2Y,...', then 'YYYY/MM/DD,...' rows."""
    rows = list(csv.reader(io.StringIO(text)))
    col = None
    out = []
    for r in rows:
        if not r:
            continue
        if col is None:
            if r[0].strip().lower() in ("date", "基準日"):
                col = next((i for i, c in enumerate(r) if c.strip().upper() == tenor), None)
            continue
        if len(r) > col and (d := _date(r[0])) and (v := _num(r[col])) is not None:
            out.append((d, v))
    if col is None:
        raise SourceUnavailable("Japan MOF file: header with the maturity columns not found")
    return out


def parse_snb_csv(text: str, code: str) -> list[tuple[date, float]]:
    """SNB data portal CSV: a few info lines, then "Date";"D0";"Value" rows (D0 = maturity, e.g. 2J)."""
    out = []
    for line in text.splitlines():
        parts = [p.strip().strip('"') for p in line.split(";")]
        if len(parts) < 3 or parts[-2] != code:
            continue
        d, v = _date(parts[0]), _num(parts[-1])
        if d and v is not None:
            out.append((d, v))
    return out


def fetch_boc(tenor: str) -> list[tuple[date, float]]:
    series = BOC_SERIES[tenor]
    start = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    return parse_boc_json(http_get(BOC_URL.format(series=series), {"start_date": start}, retries=1).json(), series)


def fetch_rba(tenor: str) -> list[tuple[date, float]]:
    sid, hint = RBA_SERIES[tenor]
    return parse_rba_csv(http_get(RBA_URL, retries=1).text, sid, hint)


def fetch_mof(tenor: str) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []
    for url in MOF_URLS:  # this month's file first; the full history fills older dates if the first is short
        r = http_get(url, retries=1)
        rows += parse_mof_csv(r.content.decode("utf-8-sig", errors="replace"), tenor)
        if len(rows) >= 40:
            break
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    return [(d, v) for d, v in rows if d >= cutoff]


def fetch_snb(tenor: str) -> list[tuple[date, float]]:
    start = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    r = http_get(SNB_URL, {"fromDate": start}, retries=1)
    return parse_snb_csv(r.text, SNB_SERIES[tenor])


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
    feeds = [("DE", "ECB AAA curve", fetch_ecb, ECB_SERIES), ("GB", "Bank of England", fetch_boe, BOE_SERIES),
             ("CA", "Bank of Canada", fetch_boc, BOC_SERIES), ("AU", "Reserve Bank of Australia", fetch_rba, RBA_SERIES),
             ("JP", "Japan Ministry of Finance", fetch_mof, {"2Y": 1, "10Y": 1}),
             ("CH", "Swiss National Bank", fetch_snb, SNB_SERIES)]
    jobs = [(country, t, (lambda f=f, t=t: f(t)), label) for country, label, f, tenors in feeds for t in tenors]
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
    # partly working: still OK, but Data health shows which series failed
    return (n, "Some yields could not be fetched: " + "; ".join(errors)) if errors else n
