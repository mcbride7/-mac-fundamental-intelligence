"""Official statistics agencies: actual values for the euro area, UK, Canada and Australia.

All free, no key:
- Eurostat (euro area): HICP and core HICP (ECOICOP ver.2 dataset from 2026), unemployment, GDP q/q
- ONS (UK): CPI, core CPI, unemployment rate, GDP q/q
- Statistics Canada: CPI y/y (from the index), unemployment rate, employment change
- ABS (Australia): unemployment rate

Values go through the same `upsert_official_release` as FRED, so a value you typed by hand is
checked against them (match -> VERIFIED, mismatch -> CONFLICT) and official revisions are kept
as new revision rows. Each agency is its own Data health source with its own Run now button.

Formats were checked against live responses in October 2026. Agencies do change their APIs, so
every series fails on its own: one broken series doesn't stop the rest, and the error names it."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import requests
from sqlalchemy.orm import Session

from app.ingestion.base import UA, SourceUnavailable
from app.models import Indicator, Source
from app.services import data_access as da

log = logging.getLogger(__name__)
TIMEOUT = 45
MONTHS = {m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                      "NOV", "DEC"], start=1)}

Fetch = Callable[[], list[tuple[str, float]]]


@dataclass
class Series:
    code: str  # indicator code
    fetch: Fetch
    note: str = ""


@dataclass
class Agency:
    key: str
    series: list[Series] = field(default_factory=list)


def _get(url: str, params: dict | None = None) -> requests.Response:
    try:
        r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise SourceUnavailable(f"could not reach {url.split('/')[2]} ({exc.__class__.__name__})") from exc
    if r.status_code != 200:
        raise SourceUnavailable(f"{url.split('/')[2]} returned {r.status_code} {_snippet(r)}".strip())
    return r


# --------------------------------------------------------------------------- Eurostat (JSON-stat 2.0)

def parse_jsonstat(data: dict, want: dict[str, list[str]]) -> list[tuple[str, float]]:
    """Pick one series out of a JSON-stat dataset.

    `want` maps a dimension id to acceptable category codes or label fragments (lower-case);
    a dimension with a single category needs no entry. Returns [(time code, value)] sorted by time."""
    ids, sizes, dims = data["id"], data["size"], data["dimension"]
    values = data.get("value", {})
    if isinstance(values, list):
        values = {str(i): v for i, v in enumerate(values) if v is not None}
    chosen: dict[str, int] = {}
    time_dim = next((d for d in ids if d in ("time", "TIME_PERIOD")), ids[-1])
    for d, n in zip(ids, sizes):
        if d == time_dim:
            continue
        cat = dims[d]["category"]
        index = cat["index"]
        if isinstance(index, list):
            index = {c: i for i, c in enumerate(index)}
        labels = {k: str(v).lower() for k, v in cat.get("label", {}).items()}
        if n == 1:
            chosen[d] = 0
            continue
        hit = None
        for w in want.get(d, []):
            wl = w.lower()
            hit = next((c for c in index if c.lower() == wl), None) or \
                next((c for c, lab in labels.items() if wl in lab), None)
            if hit:
                break
        if hit is None:
            raise SourceUnavailable(f"Eurostat: could not find {want.get(d) or 'a single value'} in dimension '{d}'")
        chosen[d] = index[hit]
    tindex = dims[time_dim]["category"]["index"]
    if isinstance(tindex, list):
        tindex = {c: i for i, c in enumerate(tindex)}
    strides, acc = [], 1
    for n in reversed(sizes):
        strides.append(acc)
        acc *= n
    strides = list(reversed(strides))
    out = []
    for tcode, tpos in tindex.items():
        pos = 0
        for d, s in zip(ids, strides):
            pos += (tpos if d == time_dim else chosen[d]) * s
        v = values.get(str(pos))
        if v is not None:
            out.append((tcode, float(v)))
    return sorted(out)


def _eurostat(dataset: str, params: dict, want: dict[str, list[str]], geos: tuple[str, ...]) -> list[tuple[str, float]]:
    last_err: Exception | None = None
    for geo in geos:
        try:
            r = _get(f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}",
                     {**params, "geo": geo, "lang": "EN"})
            pts = parse_jsonstat(r.json(), want)
            if pts:
                return [(_period(t), v) for t, v in pts]
        except (SourceUnavailable, KeyError, ValueError) as exc:
            last_err = exc
    raise SourceUnavailable(f"Eurostat {dataset}: {last_err or 'no data'}")


def _period(code: str) -> str:
    """'2026-08' / '2026M08' -> '2026-08'; '2026-Q2' / '2026Q2' -> '2026Q2'."""
    code = code.strip()
    m = re.match(r"^(\d{4})-?Q([1-4])$", code)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    m = re.match(r"^(\d{4})-?M?(\d{2})", code)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return code


HICP_WANT_UNIT = ["RCH_A", "annual rate of change"]
EUROSTAT = Agency("eurostat", [
    Series("EA_HICP_YOY", lambda: _eurostat(
        "prc_hicp_minr", {"lastTimePeriod": 4},
        {"unit": HICP_WANT_UNIT, "coicop18": ["TOTAL", "CP00", "all-items hicp"],
         "coicop": ["CP00", "TOTAL", "all-items hicp"]}, ("EA", "EA21", "EA20"))),
    Series("EA_CORE_HICP_YOY", lambda: _eurostat(
        "prc_hicp_minr", {"lastTimePeriod": 4},
        {"unit": HICP_WANT_UNIT,
         "coicop18": ["TOT_X_NRG_FOOD", "excluding energy, food, alcohol and tobacco",
                      "excluding energy and food"],
         "coicop": ["TOT_X_NRG_FOOD", "excluding energy, food, alcohol and tobacco"]}, ("EA", "EA21", "EA20"))),
    Series("EA_UNEMPLOYMENT", lambda: _eurostat(
        "une_rt_m", {"lastTimePeriod": 4, "s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"},
        {}, ("EA", "EA21", "EA20", "EA19"))),
    Series("EA_GDP_QOQ", lambda: _eurostat(
        "namq_10_gdp", {"lastTimePeriod": 4, "unit": "CLV_PCH_PRE", "s_adj": "SCA", "na_item": "B1GQ"},
        {}, ("EA", "EA21", "EA20", "EA19"))),
])


# --------------------------------------------------------------------------- ONS (UK)

def parse_ons(data: dict) -> list[tuple[str, float]]:
    out = []
    for key in ("months", "quarters"):
        for e in data.get(key) or []:
            try:
                v = float(str(e.get("value", "")).strip())
            except ValueError:
                continue
            label = (e.get("label") or e.get("date") or "").upper()
            date = (e.get("date") or label).upper()
            m = re.match(r"^(\d{4}) Q([1-4])$", date)
            if m:
                out.append((f"{m.group(1)}Q{m.group(2)}", v))
                continue
            m = re.match(r"^(\d{4}) ([A-Z]{3})$", date)
            if not (m and m.group(2) in MONTHS):
                continue
            y, mo = int(m.group(1)), MONTHS[m.group(2)]
            # rolling 3-month labour figures: date is the middle month, label the range ('2026 JUN-AUG').
            # Calendars report them under the last month, so step forward one month.
            if re.match(r"^\d{4} [A-Z]{3}-[A-Z]{3}$", label):
                y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
            out.append((f"{y}-{mo:02d}", v))
    return sorted(set(out))


def _ons(path: str, cdid: str, dataset: str, key: str) -> list[tuple[str, float]]:
    r = _get(f"https://www.ons.gov.uk/{path}/timeseries/{cdid}/{dataset}/data")
    data = r.json()
    pts = parse_ons({key: data.get(key)})
    if not pts:
        raise SourceUnavailable(f"ONS {cdid}: no values")
    return pts[-8:]


ONS = Agency("ons", [
    Series("GB_CPI_YOY", lambda: _ons("economy/inflationandpriceindices", "d7g7", "mm23", "months")),
    Series("GB_CORE_CPI_YOY", lambda: _ons("economy/inflationandpriceindices", "dko8", "mm23", "months")),
    Series("GB_UNEMPLOYMENT", lambda: _ons("employmentandlabourmarket/peoplenotinwork/unemployment",
                                           "mgsx", "lms", "months")),
    Series("GB_GDP_QOQ", lambda: _ons("economy/grossdomesticproductgdp", "ihyq", "qna", "quarters")),
])


# --------------------------------------------------------------------------- Statistics Canada (WDS)

STATCAN_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorsAndLatestNPeriods"


def parse_statcan(data: list) -> dict[int, list[tuple[str, float]]]:
    out: dict[int, list[tuple[str, float]]] = {}
    for item in data:
        if item.get("status") != "SUCCESS":
            continue
        obj = item.get("object") or {}
        pts = []
        for dp in obj.get("vectorDataPoint") or []:
            if dp.get("value") is None or not dp.get("refPer"):
                continue
            pts.append((dp["refPer"][:7], float(dp["value"])))
        out[int(obj.get("vectorId", 0))] = sorted(pts)
    return out


STATCAN_GET_URL = "https://www150.statcan.gc.ca/t1/wds/rest/getDataFromVectorByReferencePeriodRange"
HEADERS = {**UA, "Accept": "application/json, application/xml;q=0.9, */*;q=0.8"}


def _months_back(n: int) -> str:
    today = date.today()
    y, m = today.year, today.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}-{m:02d}"


def _snippet(r: requests.Response) -> str:
    return " ".join((r.text or "").split())[:120]


def _statcan(vector: int, n: int) -> list[tuple[str, float]]:
    """Two documented ways in: the POST 'latest N' call, then the GET date-range call."""
    errors = []
    attempts = [
        lambda: requests.post(STATCAN_URL, json=[{"vectorId": vector, "latestN": n}], headers=HEADERS,
                              timeout=TIMEOUT),
        lambda: requests.get(STATCAN_GET_URL, params={"vectorIds": f'"{vector}"',
                                                      "startRefPeriod": _months_back(n + 2) + "-01",
                                                      "endReferencePeriod": date.today().isoformat()},
                             headers=HEADERS, timeout=TIMEOUT),
    ]
    for attempt in attempts:
        try:
            r = attempt()
        except requests.RequestException as exc:
            errors.append(exc.__class__.__name__)
            continue
        if r.status_code != 200:
            errors.append(f"{r.status_code} {_snippet(r)}".strip())
            continue
        try:
            pts = parse_statcan(r.json()).get(vector)
        except ValueError:
            errors.append(f"not JSON: {_snippet(r)}")
            continue
        if pts:
            return pts[-n:]
        errors.append("no values")
    raise SourceUnavailable(f"Statistics Canada v{vector}: " + " | ".join(errors))


def yoy(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    by = dict(points)
    out = []
    for p, v in points:
        y, m = int(p[:4]), p[5:7]
        prev = by.get(f"{y - 1}-{m}")
        if prev:
            out.append((p, round((v / prev - 1) * 100, 1)))
    return out


def diff(points: list[tuple[str, float]]) -> list[tuple[str, float]]:
    return [(p, round(v - points[i - 1][1], 1)) for i, (p, v) in enumerate(points) if i > 0]


STATCAN = Agency("statcan", [
    Series("CA_CPI_YOY", lambda: yoy(_statcan(41690973, 16)), "CPI all-items index, Canada"),
    Series("CA_UNEMPLOYMENT", lambda: [(p, round(v, 1)) for p, v in _statcan(2062815, 4)],
           "Unemployment rate, 15+, seasonally adjusted"),
    Series("CA_EMPLOYMENT_CHANGE", lambda: diff(_statcan(2062811, 5)),
           "Employment, 15+, seasonally adjusted (thousands), month-on-month change"),
])


# --------------------------------------------------------------------------- ABS (Australia, SDMX)

def parse_sdmx_xml(text: str) -> list[tuple[str, float]]:
    root = ET.fromstring(text)
    out = []
    for el in root.iter():
        a = el.attrib
        if "TIME_PERIOD" in a and "OBS_VALUE" in a:
            try:
                out.append((_period(a["TIME_PERIOD"]), float(a["OBS_VALUE"])))
            except ValueError:
                continue
    return sorted(out)


ABS_ACCEPT = {**UA, "Accept": "application/vnd.sdmx.structurespecificdata+xml;version=2.1, application/xml"}


def _abs(flow: str, key: str) -> list[tuple[str, float]]:
    errors = []
    tries = [
        (f"https://data.api.abs.gov.au/rest/data/ABS,{flow}/{key}",
         {"startPeriod": _months_back(8), "dimensionAtObservation": "AllDimensions"}, ABS_ACCEPT),
        (f"https://data.api.abs.gov.au/rest/data/ABS,{flow}/{key}", {"startPeriod": _months_back(8)},
         {**UA, "Accept": "application/xml"}),
        # the ABS's older address for the same data
        (f"https://api.data.abs.gov.au/data/ABS,{flow}/{key}",
         {"startPeriod": _months_back(8), "dimensionAtObservation": "AllDimensions"}, ABS_ACCEPT),
    ]
    for url, params, headers in tries:
        try:
            r = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            errors.append(exc.__class__.__name__)
            continue
        if r.status_code != 200:
            errors.append(f"{url.split('/')[2]} {r.status_code} {_snippet(r)}".strip())
            continue
        try:
            pts = parse_sdmx_xml(r.text)
        except ET.ParseError:
            errors.append(f"not XML: {_snippet(r)}")
            continue
        if pts:
            return pts
        errors.append("no values")
    raise SourceUnavailable(f"ABS {flow} {key}: " + " | ".join(errors))


ABS = Agency("abs", [
    # M13 unemployment rate, persons, 15+, seasonally adjusted, Australia, monthly
    Series("AU_UNEMPLOYMENT", lambda: [(p, round(v, 1)) for p, v in _abs("LF,1.0.0", "M13.3.1599.20.AUS.M")]),
])

AGENCIES = {a.key: a for a in (EUROSTAT, ONS, STATCAN, ABS)}
OFFICIAL_BY_CODE = {s.code: a.key for a in AGENCIES.values() for s in a.series}


def run_agency(db: Session, src: Source, agency: Agency) -> int:
    from app.ingestion.fred import upsert_official_release

    n, errors, ok = 0, [], 0
    for s in agency.series:
        ind: Indicator | None = da.indicator_by_code(db, s.code)
        if ind is None:
            continue
        try:
            pts = s.fetch()
        except Exception as exc:  # one broken series must not stop the others
            errors.append(f"{s.code}: {exc}")
            continue
        ok += 1
        for period, value in pts[-3:]:
            n += upsert_official_release(db, src, ind, period, value)
        db.commit()
    if errors:
        log.warning("%s: %s", agency.key, "; ".join(errors))
        if not ok:
            raise SourceUnavailable("; ".join(errors)[:900])
    return n


def runner(key: str):
    agency = AGENCIES[key]

    def run(db: Session, src: Source) -> int:
        return run_agency(db, src, agency)

    run.__name__ = f"run_{key}"
    return run


def official_value(ind: Indicator, period: str) -> float | None:
    """Look up one official value (used to verify values typed in by hand)."""
    key = OFFICIAL_BY_CODE.get(ind.code)
    if not key:
        return None
    s = next(x for x in AGENCIES[key].series if x.code == ind.code)
    return dict(s.fetch()).get(period)
