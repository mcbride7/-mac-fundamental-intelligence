"""Deterministic parser for typed / pasted / OCR'd text (Section 66.3-66.4).

Turns free text, calendar tables, CSV, projection tables, rate-expectation
probabilities and price lists into structured rows with per-field confidence.
Used directly for typed input and as the second stage after OCR / PDF text
extraction. An LLM can refine results (see llm.py) but is never required.

Everything here is pure Python: no database, no network."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date

from app.core.enums import ContentType

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

COUNTRY_TOKENS = {
    "US": ["us", "usd", "u.s.", "united states", "america", "american"],
    "EA": ["ea", "eur", "euro area", "eurozone", "euro zone", "ez"],
    "GB": ["uk", "gb", "gbp", "united kingdom", "britain", "british"],
    "JP": ["jp", "jpy", "japan", "japanese"],
    "CH": ["ch", "chf", "switzerland", "swiss"],
    "CA": ["ca", "cad", "canada", "canadian"],
    "AU": ["au", "aud", "australia", "australian"],
    "NZ": ["nz", "nzd", "new zealand"],
    "ZA": ["za", "zar", "south africa", "sa", "south african"],
    "CN": ["cn", "cny", "china", "chinese"],
    "MX": ["mx", "mxn", "mexico", "mexican"],
}
CURRENCY_OF = {"US": "USD", "EA": "EUR", "GB": "GBP", "JP": "JPY", "CH": "CHF", "CA": "CAD",
               "AU": "AUD", "NZ": "NZD", "ZA": "ZAR", "CN": "CNY", "MX": "MXN"}
COUNTRY_OF_CCY = {v: k for k, v in CURRENCY_OF.items()}

_NUM = r"[-+−–]?\s?\d{1,3}(?:[ ,]\d{3})*(?:[.,]\d+)?|[-+−–]?\d+(?:[.,]\d+)?"
NUM_RE = re.compile(rf"(?<![A-Za-z])(?P<num>{_NUM})\s*(?P<unit>%|pct|bps|bp|k|K|m|M|bn|B|T)?(?![\w.])")

CONSENSUS_WORDS = ("consensus", "forecast", "expected", "expectation", "est", "estimate", "exp", "fcst", "f/c")
PREVIOUS_WORDS = ("previous", "prior", "prev", "last", "was")
ACTUAL_WORDS = ("actual", "act", "came in", "printed", "released at")

POLICY_WORDS = ("committee", "monetary policy", "policy rate", "federal funds", "basis points",
                "inflation", "decided", "target range", "governing council", "forward guidance",
                "labour market", "labor market", "price stability")


@dataclass
class Row:
    kind: str = "economic_release"
    fields: dict = field(default_factory=dict)
    confidence: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def set(self, key: str, value, conf: float) -> None:
        self.fields[key] = value
        self.confidence[key] = round(conf, 1)


@dataclass
class ParseResult:
    content_type: str
    content_type_confidence: float
    rows: list[Row]
    text: str = ""


# ---------------------------------------------------------------------------
# number / unit helpers
# ---------------------------------------------------------------------------

def parse_number(token: str) -> float | None:
    """Parse numbers like '3.4', '3,4', '-0.2', '1,234.5', '1 234,5', '−0.3'."""
    t = token.strip().replace("−", "-").replace("–", "-").replace(" ", "").replace(" ", "")
    if not t:
        return None
    t = t.lstrip("+")
    if "," in t and "." in t:
        # whichever separator comes last is the decimal separator
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        head, _, tail = t.rpartition(",")
        # "1,234" (thousands) vs "3,4" (decimal comma)
        if len(tail) == 3 and head.lstrip("-").isdigit() and len(head.lstrip("-")) <= 3 and "," not in head:
            t = head + tail
        else:
            t = t.replace(",", ".") if t.count(",") == 1 else t.replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def normalise_unit(unit: str | None) -> str | None:
    if not unit:
        return None
    u = unit.lower()
    return {"%": "%", "pct": "%", "bps": "bps", "bp": "bps", "k": "k", "m": "m", "bn": "bn",
            "b": "bn", "t": "tn"}.get(u, u)


def find_numbers(text: str) -> list[tuple[float, str | None, int, int]]:
    out = []
    for m in NUM_RE.finditer(text):
        raw = m.group("num")
        # skip years and times (e.g. 2026, 08:30) and reference-like numbers
        if re.fullmatch(r"(19|20)\d{2}", raw.strip()):
            continue
        before = text[max(0, m.start() - 1):m.start()]
        after = text[m.end():m.end() + 1]
        if before == ":" or after == ":":
            continue
        val = parse_number(raw)
        if val is None:
            continue
        out.append((val, normalise_unit(m.group("unit")), m.start(), m.end()))
    return out


# ---------------------------------------------------------------------------
# country / period detection
# ---------------------------------------------------------------------------

def detect_country(text: str) -> tuple[str | None, float]:
    low = f" {text.lower()} "
    # currency codes are strong signals
    for ccy, country in COUNTRY_OF_CCY.items():
        if re.search(rf"(?<![a-z]){ccy.lower()}(?![a-z])", low):
            return country, 90.0
    for country, toks in COUNTRY_TOKENS.items():
        for t in sorted(toks, key=len, reverse=True):
            if len(t) <= 2:
                if re.search(rf"(?<![a-z.]){re.escape(t)}(?![a-z])", low) and t in ("us", "uk", "ez", "sa"):
                    return country, 75.0
                continue
            if re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", low):
                return country, 85.0
    return None, 0.0


def detect_period(text: str, today: date | None = None) -> tuple[str | None, float]:
    today = today or date.today()
    low = text.lower()
    m = re.search(r"\b(20\d{2})[-/](0?[1-9]|1[0-2])\b", low)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}", 95.0
    m = re.search(r"\bq([1-4])\s*[-/ ]?\s*(20\d{2})\b|\b(20\d{2})\s*q([1-4])\b", low)
    if m:
        q = m.group(1) or m.group(4)
        y = m.group(2) or m.group(3)
        return f"{y}Q{q}", 95.0
    m = re.search(r"\bq([1-4])\b", low)
    if m:
        q = int(m.group(1))
        y = today.year if q <= (today.month - 1) // 3 + 1 else today.year - 1
        return f"{y}Q{q}", 60.0
    for name in sorted(MONTHS, key=len, reverse=True):
        mm = re.search(rf"\b{name}\b\.?\s*(20\d{{2}})?", low)
        if mm:
            month = MONTHS[name]
            if mm.group(1):
                return f"{mm.group(1)}-{month:02d}", 95.0
            year = today.year if month <= today.month else today.year - 1
            return f"{year}-{month:02d}", 70.0
    return None, 0.0


def detect_transform(text: str) -> str | None:
    low = text.lower()
    if re.search(r"\b(y/y|yoy|y-o-y|year[- ]on[- ]year|annual)\b", low):
        return "yoy"
    if re.search(r"\b(m/m|mom|m-o-m|month[- ]on[- ]month|monthly)\b", low):
        return "mom"
    if re.search(r"\b(q/q|qoq|quarter[- ]on[- ]quarter)\b", low):
        return "qoq"
    return None


# ---------------------------------------------------------------------------
# content-type detection
# ---------------------------------------------------------------------------

TIME_RE = re.compile(r"^\s*(\d{1,2}:\d{2})\s*(am|pm)?\b", re.I)
CCY_RE = re.compile(r"\b(USD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|ZAR|CNY|MXN)\b")


def _looks_like_table_line(line: str) -> bool:
    return bool((TIME_RE.search(line) or CCY_RE.search(line)) and len(find_numbers(line)) >= 1)


def detect_content_type(text: str) -> tuple[str, float]:
    low = text.lower()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    policy_hits = sum(1 for w in POLICY_WORDS if w in low)
    if len(text) > 400 and policy_hits >= 3 and len(find_numbers(text)) < len(text) / 40:
        return ContentType.CB_STATEMENT.value, min(95.0, 55 + policy_hits * 7)
    if re.search(r"\b(projection|projections|summary of economic projections|staff projections|sep)\b", low) \
            and len(re.findall(r"\b20\d{2}\b", text)) >= 2:
        return ContentType.CB_PROJECTIONS.value, 85.0
    if re.search(r"\b(hike|raise)\b", low) and re.search(r"\b(hold|unchanged|pause|cut)\b", low) \
            and "%" in text and re.search(r"probabilit|pricing|odds|chance|implied", low):
        return ContentType.RATE_EXPECTATIONS.value, 85.0
    if re.search(r"\b[A-Z]{3}/[A-Z]{3}\b", text) or re.search(r"\b(xau|gold|brent|wti|bitcoin|btc|\d{1,2}y)\b", low):
        if sum(1 for ln in lines if len(find_numbers(ln)) == 1) >= max(1, len(lines) // 2) and \
                not re.search(r"\b(cpi|gdp|payroll|pmi|unemployment)\b", low):
            return ContentType.MARKET_PRICES.value, 75.0
    if text.lstrip().lower().startswith(("indicator,", "event,", "date,", "indicator\t", "event\t")):
        return ContentType.CALENDAR.value, 90.0
    table_lines = sum(1 for ln in lines if _looks_like_table_line(ln))
    if table_lines >= 2:
        return ContentType.CALENDAR.value, min(95.0, 60 + table_lines * 5)
    if find_numbers(text):
        return ContentType.ECONOMIC_RELEASE.value, 70.0
    if len(text) > 200:
        return ContentType.SPEECH.value, 40.0
    return ContentType.UNKNOWN.value, 0.0


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------

def _label_for(segment: str) -> str | None:
    low = segment.lower()
    for w in CONSENSUS_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", low):
            return "consensus"
    for w in PREVIOUS_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", low):
            return "previous"
    for w in ACTUAL_WORDS:
        if re.search(rf"\b{re.escape(w)}\b", low):
            return "actual"
    return None


_FILLER = r"\b(consensus|forecast|expected|expectations?|estimates?|est|exp|previous|prior|prev|last|actual|" \
          r"came in at|came in|printed|released at|vs\.?|versus|against|flash|prelim|preliminary|final|" \
          r"at|was|of|is|the|for|in|rose|fell|to)\b"


def _strip_name(segment: str) -> str:
    s = re.sub(NUM_RE, " ", segment)
    s = re.sub(r"\b(y/y|m/m|q/q|yoy|mom|qoq)\b", " ", s, flags=re.I)
    for name in sorted(MONTHS, key=len, reverse=True):
        s = re.sub(rf"\b{name}\b\.?", " ", s, flags=re.I)
    s = re.sub(r"\b20\d{2}\b", " ", s)
    s = re.sub(_FILLER, " ", s, flags=re.I)
    s = re.sub(r"[%()]", " ", s)
    return re.sub(r"\s+", " ", s).strip(" :-,;/")


def _labelled_numbers(segment: str) -> list[tuple[float, str | None, str | None]]:
    """Return (value, unit, label) for each number; the label comes from the words
    just before the number, or failing that, just after it ('2.2% expected')."""
    nums = find_numbers(segment)
    out = []
    for i, (val, unit, start, end) in enumerate(nums):
        prev_end = nums[i - 1][3] if i else 0
        next_start = nums[i + 1][2] if i + 1 < len(nums) else len(segment)
        prefix = segment[prev_end:start]
        suffix = segment[end:next_start]
        label = _label_for(prefix[-25:])
        if label is None:
            s_label = _label_for(suffix[:25])
            # 'X% previous Y%': the word after X introduces Y, so it is not X's label
            belongs_to_next = (i + 1 < len(nums) and s_label is not None
                               and not re.search(r"[,(;]|\bvs\b|\band\b", suffix, re.I))
            label = None if belongs_to_next else s_label
        out.append((val, unit, label))
    return out


def parse_natural(text: str, today: date | None = None) -> list[Row]:
    """'US CPI September 3.4% y/y, core 3.1%, consensus 3.1%, previous 3.2%'"""
    rows: list[Row] = []
    country, c_conf = detect_country(text)
    period, p_conf = detect_period(text, today)
    # split on ';', newlines and commas that are not decimal commas ('3,4%')
    segments = [s for s in re.split(r"[;\n]+|,(?!\d)", text) if s and s.strip()]
    main: Row | None = None
    for seg in segments:
        labelled = _labelled_numbers(seg)
        if not labelled:
            continue
        name = _strip_name(seg)
        first_label = labelled[0][2]
        is_core = main is not None and bool(re.search(r"\bcore\b", seg, re.I)) and first_label is None
        new_named = main is not None and first_label is None and len(name) > 3 and not is_core
        if main is None or is_core or new_named:
            if is_core:
                base = main.fields.get("indicator_text", "")
                name = base if "core" in base.lower() else f"core {base}".strip()
            r = Row()
            r.set("indicator_text", name, 80.0 if name else 20.0)
            if country:
                r.set("country", country, c_conf)
                r.set("currency", CURRENCY_OF[country], c_conf)
            if period:
                r.set("reference_period", period, p_conf)
            tr = detect_transform(seg) or (main.fields.get("transform") if main else None) or detect_transform(text)
            if tr:
                r.set("transform", tr, 85.0)
            rows.append(r)
            target = r
            if main is None:
                main = r
        else:
            target = main
        for val, unit, label in labelled:
            key = label or "actual"
            if key in target.fields:
                target.warnings.append(f"Additional value {val} for '{key}' ignored")
                continue
            target.set(key, val, 90.0 if label or key == "actual" else 60.0)
            if unit and "unit" not in target.fields:
                target.set("unit", unit, 88.0)
    return rows


def _header_order(line: str) -> list[str] | None:
    low = line.lower()
    cols = []
    for m in re.finditer(r"actual|forecast|consensus|previous|prior|cons\.?|fcst", low):
        w = m.group(0)
        cols.append("actual" if w.startswith("act") else "previous" if w in ("previous", "prior")
                    else "consensus")
    return cols if len(cols) >= 2 else None


def parse_calendar_table(text: str, today: date | None = None) -> list[Row]:
    rows: list[Row] = []
    order = ["actual", "consensus", "previous"]  # default (Investing.com / ForexFactory column order)
    period_global, pg_conf = detect_period(text, today)
    for line in text.splitlines():
        if not line.strip():
            continue
        h = _header_order(line)
        if h and not find_numbers(line):
            order = h
            continue
        nums = find_numbers(line)
        if not nums:
            continue
        r = Row(kind="economic_release")
        tm = TIME_RE.search(line)
        if tm:
            r.set("release_time", tm.group(1), 90.0)
        ccy = CCY_RE.search(line)
        if ccy:
            c = COUNTRY_OF_CCY[ccy.group(1)]
            r.set("currency", ccy.group(1), 92.0)
            r.set("country", c, 92.0)
        else:
            c, cc = detect_country(line)
            if c:
                r.set("country", c, cc)
                r.set("currency", CURRENCY_OF[c], cc)
        first_num_pos = nums[0][2]
        name_part = line[:first_num_pos]
        if tm:
            name_part = name_part[tm.end():]
        if ccy:
            name_part = name_part.replace(ccy.group(1), " ")
        name = re.sub(r"\s+", " ", name_part).strip(" |-:\t")
        r.set("indicator_text", name, 80.0 if name else 20.0)
        tr = detect_transform(name)
        if tr:
            r.set("transform", tr, 85.0)
        period, p_conf = detect_period(name, today)
        if period:
            r.set("reference_period", period, p_conf)
        elif period_global:
            r.set("reference_period", period_global, max(40.0, pg_conf - 20))
        n = len(nums)
        if n >= len(order):
            for key, (val, unit, *_) in zip(order, nums[: len(order)]):
                r.set(key, val, 85.0)
                if unit and "unit" not in r.fields:
                    r.set("unit", unit, 85.0)
        elif n == 2 and len(order) == 3 and order[0] == "actual":
            r.set("consensus", nums[0][0], 65.0)
            r.set("previous", nums[1][0], 65.0)
            r.warnings.append("Only two values found; assumed forecast and previous (actual not yet released)")
            if nums[0][1]:
                r.set("unit", nums[0][1], 80.0)
        else:
            r.set("actual", nums[0][0], 50.0)
            if nums[0][1]:
                r.set("unit", nums[0][1], 80.0)
            r.warnings.append("Column order unclear; first value treated as actual")
        rows.append(r)
    return rows


CSV_KEYS = {
    "indicator": "indicator_text", "event": "indicator_text", "name": "indicator_text",
    "period": "reference_period", "reference period": "reference_period",
    "actual": "actual", "previous": "previous", "prior": "previous", "forecast": "consensus",
    "consensus": "consensus", "unit": "unit", "date": "release_date", "time": "release_time",
    "country": "country", "currency": "currency", "importance": "importance",
    "code": "indicator_code", "indicator_code": "indicator_code",
}


def parse_csv(text: str, today: date | None = None) -> list[Row]:
    sample = text[:2000]
    delim = "\t" if sample.count("\t") > sample.count(",") else ("|" if sample.count("|") > sample.count(",") else ",")
    reader = csv.DictReader(io.StringIO(text.strip()), delimiter=delim)
    rows: list[Row] = []
    for rec in reader:
        r = Row()
        for k, v in rec.items():
            if k is None or v is None:
                continue
            key = CSV_KEYS.get(k.strip().lower())
            v = v.strip()
            if not key or v == "":
                continue
            if key in ("actual", "previous", "consensus"):
                nums = find_numbers(v)
                if nums:
                    r.set(key, nums[0][0], 98.0)
                    if nums[0][1] and "unit" not in r.fields:
                        r.set("unit", nums[0][1], 95.0)
                else:
                    r.warnings.append(f"Could not read number in column '{k}': {v!r}")
            elif key == "reference_period":
                p, pc = detect_period(v, today)
                r.set(key, p or v, 98.0 if p else 60.0)
            elif key == "country":
                c, _ = detect_country(v)
                r.set("country", c or v.upper(), 95.0)
            else:
                r.set(key, v, 98.0)
        if "country" not in r.fields and "currency" in r.fields:
            c = COUNTRY_OF_CCY.get(r.fields["currency"].upper())
            if c:
                r.set("country", c, 95.0)
        if r.fields:
            rows.append(r)
    return rows


def parse_projection_table(text: str) -> list[Row]:
    """Fed SEP / ECB staff projections style:
        Variable        2026  2027  2028  Longer run
        Change in real GDP  1.4  1.6  1.8  1.8
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    years: list[str] = []
    rows: list[Row] = []
    var_map = [
        (r"core\s*(pce|hicp|cpi|inflation)", "core_inflation"),
        (r"(pce|hicp|cpi|inflation)", "inflation"),
        (r"(gdp|output|growth)", "gdp"),
        (r"unemployment", "unemployment"),
        (r"(federal funds|policy rate|bank rate|deposit|cash rate|repo rate|interest rate)", "policy_rate"),
    ]
    for ln in lines:
        ys = re.findall(r"\b(20\d{2})\b", ln)
        if len(ys) >= 2 and len(find_numbers(ln)) == 0:
            years = ys + (["longer_run"] if re.search(r"longer\s*run", ln, re.I) else [])
            continue
        if not years:
            continue
        nums = find_numbers(ln)
        if not nums:
            continue
        var = None
        for pat, name in var_map:
            if re.search(pat, ln, re.I):
                var = name
                break
        if var is None:
            continue
        for period, (val, *_rest) in zip(years, nums):
            r = Row(kind="cb_projection")
            r.set("variable", var, 85.0)
            r.set("target_period", period, 90.0)
            r.set("value", val, 90.0)
            r.set("label_text", re.sub(NUM_RE, "", ln).strip(), 80.0)
            rows.append(r)
    return rows


def parse_rate_expectations(text: str) -> list[Row]:
    r = Row(kind="rate_expectation")
    low = text.lower()
    for key, pat in (("prob_cut", r"(cut|ease|lower)[^\d%]{0,20}(\d+(?:[.,]\d+)?)\s*%"),
                     ("prob_hold", r"(hold|unchanged|pause|no change)[^\d%]{0,20}(\d+(?:[.,]\d+)?)\s*%"),
                     ("prob_hike", r"(hike|raise|increase)[^\d%]{0,20}(\d+(?:[.,]\d+)?)\s*%")):
        m = re.search(pat, low)
        if m:
            r.set(key, parse_number(m.group(2)), 85.0)
    # also "25% cut" ordering
    for key, pat in (("prob_cut", r"(\d+(?:[.,]\d+)?)\s*%\s*(?:probability\s*(?:of\s*)?(?:a\s*)?)?(cut)"),
                     ("prob_hold", r"(\d+(?:[.,]\d+)?)\s*%\s*(?:probability\s*(?:of\s*)?(?:a\s*)?)?(hold)"),
                     ("prob_hike", r"(\d+(?:[.,]\d+)?)\s*%\s*(?:probability\s*(?:of\s*)?(?:a\s*)?)?(hike)")):
        if key not in r.fields:
            m = re.search(pat, low)
            if m:
                r.set(key, parse_number(m.group(1)), 75.0)
    for code, toks in (("FED", ["fed", "fomc"]), ("ECB", ["ecb"]), ("BOE", ["boe", "bank of england"]),
                       ("BOJ", ["boj"]), ("SARB", ["sarb"]), ("RBA", ["rba"]), ("BOC", ["boc", "bank of canada"]),
                       ("RBNZ", ["rbnz"]), ("SNB", ["snb"]), ("BANXICO", ["banxico"])):
        if any(re.search(rf"\b{t}\b", low) for t in toks):
            r.set("central_bank_code", code, 85.0)
            break
    total = sum(r.fields.get(k, 0) or 0 for k in ("prob_cut", "prob_hold", "prob_hike"))
    if r.fields and abs(total - 100) > 2:
        r.warnings.append(f"Probabilities sum to {total:.1f}%, not 100%")
    return [r] if any(k.startswith("prob_") for k in r.fields) else []


SYMBOL_ALIASES = {
    "gold": "XAUUSD", "xau/usd": "XAUUSD", "silver": "XAGUSD", "brent": "BRENT", "wti": "WTI", "oil": "WTI",
    "bitcoin": "BTCUSD", "btc": "BTCUSD", "btc/usd": "BTCUSD", "s&p 500": "SPX", "spx": "SPX", "dxy": "DXY",
}


def parse_market_prices(text: str) -> list[Row]:
    rows = []
    for ln in text.splitlines():
        nums = find_numbers(ln)
        if not nums:
            continue
        low = ln.lower()
        m = re.search(r"\b([A-Z]{3})/([A-Z]{3})\b", ln)
        y = re.search(r"\b(us|de|uk|gb|jp|za|ea)\s*(\d{1,2})\s*y(?:r|ear)?\b", low) or \
            re.search(r"\b(\d{1,2})\s*-?\s*y(?:ea)?r?\s+(us|de|uk|gb|jp|za)\b", low)
        r = Row(kind="market_price")
        if m:
            r.set("symbol", m.group(1) + m.group(2), 92.0)
            r.set("price", nums[0][0], 90.0)
        elif y:
            g = y.groups()
            country, tenor = (g[0], g[1]) if g[0].isalpha() else (g[1], g[0])
            country = {"uk": "GB", "de": "DE"}.get(country, country.upper())
            r.kind = "bond_yield"
            r.set("country", country, 85.0)
            r.set("tenor", f"{int(tenor)}Y", 90.0)
            r.set("yield_pct", nums[-1][0], 88.0)
        else:
            sym = next((v for k, v in SYMBOL_ALIASES.items() if k in low), None)
            if not sym:
                continue
            r.set("symbol", sym, 80.0)
            r.set("price", nums[0][0], 88.0)
        rows.append(r)
    return rows


def parse_text(text: str, today: date | None = None, content_type: str | None = None) -> ParseResult:
    text = text.replace("\r\n", "\n").strip()
    ctype, cconf = (content_type, 100.0) if content_type else detect_content_type(text)
    if ctype == ContentType.CB_STATEMENT.value or ctype == ContentType.SPEECH.value:
        r = Row(kind="cb_statement" if ctype == ContentType.CB_STATEMENT.value else "speech")
        r.set("text", text, 95.0)
        return ParseResult(ctype, cconf, [r], text)
    if ctype == ContentType.CB_PROJECTIONS.value:
        return ParseResult(ctype, cconf, parse_projection_table(text), text)
    if ctype == ContentType.RATE_EXPECTATIONS.value:
        return ParseResult(ctype, cconf, parse_rate_expectations(text), text)
    if ctype == ContentType.MARKET_PRICES.value:
        return ParseResult(ctype, cconf, parse_market_prices(text), text)
    if ctype == ContentType.CALENDAR.value:
        first = text.lstrip().split("\n", 1)[0].lower()
        if ("," in first or "\t" in first or "|" in first) and re.search(r"indicator|event|actual|name", first):
            return ParseResult(ctype, cconf, parse_csv(text, today), text)
        return ParseResult(ctype, cconf, parse_calendar_table(text, today), text)
    return ParseResult(ctype, cconf, parse_natural(text, today), text)
