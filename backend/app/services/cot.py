"""COT positioning: markets, CFTC fetch, file import, weekly prices, board and market views.

Source: CFTC Commitments of Traders, Legacy report, futures only. Positions are as of Tuesday and are
published the following Friday at 3:30 pm US Eastern (21:30 or 22:30 South African time).
New weeks come from the CFTC Public Reporting API; whole years can also be merged from the CFTC's
history files (deacot<YEAR>.zip). Weekly prices come from FRED's free daily series where they exist,
from Twelve Data for gold and silver, or are typed in. Typed values are never overwritten.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import re
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import cot as ca
from app.ingestion.base import SourceUnavailable, http_get
from app.models import CotWeek, IndicatorObservation, MarketPrice, Source

log = logging.getLogger(__name__)

# code: (name, group, currency it stands for (or None), price note)
MARKETS: dict[str, tuple[str, str, str | None, str]] = {
    "088691": ("Gold", "Metals", None, "USD per oz"),
    "084691": ("Silver", "Metals", None, "USD per oz"),
    "085692": ("Copper", "Metals", None, "typed in"),
    "067651": ("WTI crude oil", "Energy", None, "USD per barrel"),
    "023651": ("Natural gas (Henry Hub)", "Energy", None, "USD per MMBtu"),
    "099741": ("Euro (EUR)", "Currencies", "EUR", "USD per EUR"),
    "097741": ("Japanese yen (JPY)", "Currencies", "JPY", "USD per JPY"),
    "096742": ("British pound (GBP)", "Currencies", "GBP", "USD per GBP"),
    "232741": ("Australian dollar (AUD)", "Currencies", "AUD", "USD per AUD"),
    "090741": ("Canadian dollar (CAD)", "Currencies", "CAD", "USD per CAD"),
    "092741": ("Swiss franc (CHF)", "Currencies", "CHF", "USD per CHF"),
    "122741": ("South African rand (ZAR)", "Currencies", "ZAR", "USD per ZAR"),
    "098662": ("US dollar index", "Currencies", "USD", "typed in"),
    "13874A": ("S&P 500 E-mini", "Equity indices", None, "index points"),
    "209742": ("Nasdaq-100 E-mini", "Equity indices", None, "index points"),
    "043602": ("10-year T-note", "Rates", None, "10-year yield, %"),
    "133741": ("Bitcoin (CME)", "Crypto", None, "USD"),
    "002602": ("Corn", "Agriculture", None, "typed in"),
    "005602": ("Soybeans", "Agriculture", None, "typed in"),
}
GROUP_ORDER = ["Currencies", "Metals", "Energy", "Equity indices", "Rates", "Crypto", "Agriculture"]

# weekly price sources: FRED daily series (and whether to invert it so a rising line = that currency stronger)
PRICE_FRED = {
    "067651": ("DCOILWTICO", False), "023651": ("DHHNGSP", False), "099741": ("DEXUSEU", False),
    "097741": ("DEXJPUS", True), "096742": ("DEXUSUK", False), "232741": ("DEXUSAL", False),
    "090741": ("DEXCAUS", True), "092741": ("DEXSZUS", True), "122741": ("DEXSFUS", True),
    "13874A": ("SP500", False), "209742": ("NASDAQ100", False), "043602": ("DGS10", False),
    "133741": ("CBBTCUSD", False),
}
PRICE_MARKET = {"088691": "XAUUSD", "084691": "XAGUSD"}  # Twelve Data symbols
PRICE_PREFIX = "COTPX:"

API = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
BUNDLED = Path(__file__).resolve().parent.parent / "data" / "cot_history.json.gz"

_norm = lambda h: re.sub(r"[^a-z0-9]", "", str(h).lower())  # noqa: E731
FIELDS = {
    "d": ["reportdateasyyyymmdd", "asofdateinformyyyymmdd", "reportdate"],
    "code": ["cftccontractmarketcode"],
    "oi": ["openinterestall"],
    "ncl": ["noncommpositionslongall", "noncommercialpositionslongall"],
    "ncs": ["noncommpositionsshortall", "noncommercialpositionsshortall"],
    "cl": ["commpositionslongall", "commercialpositionslongall"],
    "cs": ["commpositionsshortall", "commercialpositionsshortall"],
    "nrl": ["nonreptpositionslongall", "nonreportablepositionslongall"],
    "nrs": ["nonreptpositionsshortall", "nonreportablepositionsshortall"],
}


# ---------------------------------------------------------------- parsing and storing

def to_records(objs: list[dict]) -> list[dict]:
    """CFTC rows (API JSON, history file CSV, or a CSV export) -> our week records for tracked markets."""
    out = []
    for o in objs:
        n = {_norm(k): v for k, v in o.items()}

        def get(k):
            for a in FIELDS[k]:
                if n.get(a) not in (None, ""):
                    return n[a]
            return None

        code = str(get("code") or "").strip()
        d = str(get("d") or "")[:10]
        if code not in MARKETS or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            continue
        try:
            rec = {"code": code, "d": d}
            for k in ("oi", "ncl", "ncs", "cl", "cs", "nrl", "nrs"):
                v = get(k)
                rec[k] = None if v is None else int(float(str(v).replace(",", "").strip()))
        except ValueError:
            continue
        if None in (rec["oi"], rec["ncl"], rec["ncs"], rec["cl"], rec["cs"]):
            continue
        out.append(rec)
    return out


def read_file(name: str, data: bytes) -> list[dict]:
    """A CFTC history zip, its .txt/.csv, or a JSON/CSV export."""
    texts = []
    if name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            texts = [z.read(n).decode("latin-1") for n in z.namelist() if n.lower().endswith((".txt", ".csv"))]
    else:
        texts = [data.decode("utf-8-sig", errors="replace")]
    recs = []
    for t in texts:
        t = t.strip()
        if t.startswith("["):
            recs += to_records(json.loads(t))
        else:
            r = csv.DictReader(io.StringIO(t))
            recs += to_records([{(k or "").strip(): v for k, v in row.items()} for row in r])
    return recs


def upsert(db: Session, recs: list[dict], method: str) -> tuple[int, int]:
    """Add new weeks; refresh positions of existing ones (prices and typed weeks are kept)."""
    added = updated = 0
    for r in recs:
        d = date.fromisoformat(r["d"])
        w = db.scalar(select(CotWeek).where(CotWeek.code == r["code"], CotWeek.report_date == d))
        if w is None:
            db.add(CotWeek(code=r["code"], report_date=d, oi=r["oi"], ncl=r["ncl"], ncs=r["ncs"], cl=r["cl"],
                           cs=r["cs"], nrl=r.get("nrl"), nrs=r.get("nrs"), input_method=method))
            added += 1
        elif w.input_method != "manual":
            changed = any(getattr(w, k) != r.get(k) for k in ("oi", "ncl", "ncs", "cl", "cs", "nrl", "nrs"))
            if changed:
                for k in ("oi", "ncl", "ncs", "cl", "cs", "nrl", "nrs"):
                    setattr(w, k, r.get(k))
                updated += 1
    db.commit()
    return added, updated


def import_bundled(db: Session) -> int:
    """First start: load the stored history (Jan 2025 onwards) that came with the COT tracker."""
    if db.scalar(select(func.count()).select_from(CotWeek)) or not BUNDLED.exists():
        return 0
    with gzip.open(BUNDLED, "rt") as f:
        data = json.load(f)
    recs = [{"code": code, **row} for code, rows in data.items() for row in rows]
    for r in recs:
        if r.get("px") is not None:
            r["price"] = r["px"]
    added, _ = upsert(db, recs, "bundled")
    log.info("COT: loaded %s stored weeks", added)
    return added


# ---------------------------------------------------------------- CFTC fetch

def fetch_new(db: Session, since: date | None = None) -> list[dict]:
    last = since or db.scalar(select(func.max(CotWeek.report_date)))
    start = (last or date(2025, 1, 1) - timedelta(days=1))
    codes = ",".join(f"'{c}'" for c in MARKETS)
    where = (f"report_date_as_yyyy_mm_dd > '{start.isoformat()}T00:00:00.000' AND "
             f"cftc_contract_market_code in({codes})")
    r = http_get(API, {"$where": where, "$limit": 5000, "$order": "report_date_as_yyyy_mm_dd"})
    try:
        rows = r.json()
    except ValueError as exc:
        raise SourceUnavailable("The CFTC sent something that isn't data") from exc
    if not isinstance(rows, list):
        raise SourceUnavailable(f"Unexpected CFTC reply: {str(rows)[:200]}")
    return to_records(rows)


# ---------------------------------------------------------------- prices

def _collect_price_series(db: Session) -> list[str]:
    from app.ingestion.fred import fetch_observations

    failed = []
    for code, (series, _) in PRICE_FRED.items():
        key = PRICE_PREFIX + series
        have = {d for (d,) in db.execute(select(IndicatorObservation.obs_date).where(IndicatorObservation.series == key))}
        try:
            obs = fetch_observations(series, "2024-12-01")
        except Exception as exc:
            failed.append(f"{series}: {exc}")
            continue
        for d, v in obs:
            if d not in have:
                db.add(IndicatorObservation(series=key, obs_date=d, value=v))
    db.commit()
    return failed


def _value_near(db: Session, series_key: str, day: date) -> float | None:
    """Closing value on the report Tuesday, or the nearest earlier day within 3 days."""
    row = db.scalar(select(IndicatorObservation).where(IndicatorObservation.series == series_key,
                                                       IndicatorObservation.obs_date <= day,
                                                       IndicatorObservation.obs_date >= day - timedelta(days=3))
                    .order_by(IndicatorObservation.obs_date.desc()))
    return row.value if row else None


def price_for(db: Session, code: str, day: date) -> tuple[float, str] | None:
    if code in PRICE_FRED:
        series, invert = PRICE_FRED[code]
        v = _value_near(db, PRICE_PREFIX + series, day)
        if v:
            return (round(1 / v, 9) if invert else v), "FRED"
    if code in PRICE_MARKET:
        sym = PRICE_MARKET[code]
        if code == "088691":
            v = _value_near(db, "RISK:gold", day)
            if v:
                return v, "Twelve Data"
        end = datetime.combine(day, time(23, 59), tzinfo=timezone.utc)
        p = db.scalar(select(MarketPrice).where(MarketPrice.symbol == sym, MarketPrice.ts <= end,
                                                MarketPrice.ts >= end - timedelta(days=3))
                      .order_by(MarketPrice.ts.desc()))
        if p:
            return p.price, "Twelve Data"
    return None


def fill_prices(db: Session) -> int:
    n = 0
    for w in db.scalars(select(CotWeek).where(CotWeek.price.is_(None))):
        got = price_for(db, w.code, w.report_date)
        if got:
            w.price, w.price_source = got
            n += 1
    db.commit()
    return n


def run_cftc(db: Session, src: Source) -> int:
    """Worker job: add any new COT weeks, then fill weekly prices."""
    import_bundled(db)
    recs = fetch_new(db)
    added, _ = upsert(db, recs, "automated")
    failed = _collect_price_series(db)
    priced = fill_prices(db)
    if failed:
        log.info("COT prices: some FRED series failed: %s", "; ".join(failed))
    log.info("COT: %s new market-weeks, %s prices filled", added, priced)
    return added


# ---------------------------------------------------------------- views

def rows_of(db: Session, code: str) -> list[dict]:
    out = []
    for w in db.scalars(select(CotWeek).where(CotWeek.code == code).order_by(CotWeek.report_date)):
        out.append({"d": w.report_date.isoformat(), "oi": w.oi, "ncl": w.ncl, "ncs": w.ncs, "cl": w.cl, "cs": w.cs,
                    "nrl": w.nrl, "nrs": w.nrs, "price": w.price, "price_source": w.price_source,
                    "input_method": w.input_method})
    return out


def summary(code: str, rows: list[dict]) -> dict:
    name, group, ccy, note = MARKETS[code]
    base = {"code": code, "name": name, "group": group, "currency": ccy, "price_note": note, "weeks": len(rows)}
    if not rows:
        return base | {"report_date": None}
    spec, comm = ca.net(rows, "spec"), ca.net(rows, "comm")
    last = rows[-1]
    return base | {
        "report_date": last["d"], "spec_net": spec[-1], "spec_change": spec[-1] - spec[-2] if len(spec) > 1 else None,
        "comm_net": comm[-1], "oi": last["oi"], "oi_change": last["oi"] - rows[-2]["oi"] if len(rows) > 1 else None,
        "spec_long_pct": round(100 * last["ncl"] / (last["ncl"] + last["ncs"]), 1) if (last["ncl"] + last["ncs"]) else None,
        "cot_index_52": ca.cot_index(spec, 52), "cot_index_156": ca.cot_index(spec, 156) if len(spec) >= 104 else None,
        "comm_index_52": ca.cot_index(comm, 52), "price": last["price"],
        "signals": ca.signals(rows),
    }


def board(db: Session) -> list[dict]:
    out = [summary(c, rows_of(db, c)) for c in MARKETS]
    out.sort(key=lambda s: (GROUP_ORDER.index(s["group"]), s["name"]))
    return out


def market(db: Session, code: str, weeks: int | None = None) -> dict:
    if code not in MARKETS:
        raise LookupError(f"Unknown market {code}")
    rows = rows_of(db, code)
    shown = rows[-weeks:] if weeks else rows
    spec, comm, small = ca.net(rows, "spec"), ca.net(rows, "comm"), ca.net(rows, "small")
    idx = [ca.cot_index(spec[: i + 1], 52) for i in range(len(spec))]
    series = []
    for i, r in enumerate(rows):
        series.append(r | {"spec_net": spec[i], "comm_net": comm[i], "small_net": small[i],
                           "spec_change": spec[i] - spec[i - 1] if i else None, "cot_index": idx[i]})
    return summary(code, rows) | {"series": series[-len(shown):] if shown else []}


# ---------------------------------------------------------------- editing

def set_price(db: Session, code: str, day: date, price: float | None) -> CotWeek:
    w = db.scalar(select(CotWeek).where(CotWeek.code == code, CotWeek.report_date == day))
    if w is None:
        raise LookupError("No report stored for that week")
    w.price = price
    w.price_source = "manual" if price is not None else None
    db.commit()
    return w


def paste_prices(db: Session, code: str, text: str) -> dict:
    """Lines of 'date, price'. Each goes to the stored report dated on, or up to 3 days before, that date."""
    weeks = list(db.scalars(select(CotWeek).where(CotWeek.code == code)))
    saved, skipped = 0, []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"(\d{4}-\d{2}-\d{2})\s*[,;\t ]\s*([-+]?[\d,]*\.?\d+)", line)
        if not m:
            skipped.append(line)
            continue
        d = date.fromisoformat(m.group(1))
        target = next((w for w in weeks if 0 <= (d - w.report_date).days <= 3), None)
        if target is None:
            skipped.append(line)
            continue
        target.price, target.price_source = float(m.group(2).replace(",", "")), "manual"
        saved += 1
    db.commit()
    return {"saved": saved, "skipped": skipped}


def save_week(db: Session, code: str, rec: dict) -> CotWeek:
    """Add or correct one week by hand."""
    if code not in MARKETS:
        raise LookupError(f"Unknown market {code}")
    d = date.fromisoformat(rec["d"])
    w = db.scalar(select(CotWeek).where(CotWeek.code == code, CotWeek.report_date == d))
    if w is None:
        w = CotWeek(code=code, report_date=d, oi=0, ncl=0, ncs=0, cl=0, cs=0)
        db.add(w)
    for k in ("oi", "ncl", "ncs", "cl", "cs", "nrl", "nrs"):
        if rec.get(k) is not None:
            setattr(w, k, int(rec[k]))
    if "price" in rec:
        w.price = rec["price"]
        w.price_source = "manual" if rec["price"] is not None else None
    w.input_method = "manual"
    db.commit()
    return w
