"""Shortcuts to each central bank's official monetary policy statement and projections.

For every bank there are two shortcuts:
  statement   - the latest policy decision / monetary policy statement
  projections - the latest staff forecasts (inflation, growth, unemployment, policy rate)

Each shortcut has:
  page   - the official page a person opens in the browser (always shown as a link)
  finder - optional rules for finding the newest document on that page automatically:
           the page to read, a pattern for the document links, an optional pattern for the link text,
           and how to pick the newest one ("max" = largest date in the link, "first" = first on the page).

Banks redesign their websites now and then. When a finder stops matching, the app says so and the
person pastes the document's link instead - the link box on the same panel does the same import.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin

from app.ingestion.base import SourceUnavailable, http_get

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


@dataclass
class Finder:
    listing: str                     # page to read; {year} is replaced by the current year (then last year)
    href: str                        # regex for the document link (matched against the full link)
    text: str | None = None          # optional regex for the link's visible text
    pick: str = "max"                # "max" (newest date found in the link) or "first" (first on the page)
    suffix: str = ""                 # appended to the chosen link (e.g. a chapter page)


@dataclass
class Shortcut:
    page: str
    label: str
    finder: Finder | None = None
    note: str = ""


@dataclass
class BankShortcuts:
    code: str
    statement: Shortcut
    projections: Shortcut
    extra: list[tuple[str, str]] = field(default_factory=list)  # (label, url) more official pages


CATALOGUE: dict[str, BankShortcuts] = {
    "FED": BankShortcuts(
        "FED",
        Shortcut("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "FOMC statement",
                 Finder("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        r"/newsevents/pressreleases/monetary(\d{8})a\.htm")),
        Shortcut("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                 "Summary of Economic Projections (dot plot)",
                 Finder("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        r"/monetarypolicy/fomcprojtabl(\d{8})\.htm"),
                 "Published at the March, June, September and December meetings."),
        [("Minutes and calendar", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
         ("Speeches", "https://www.federalreserve.gov/newsevents/speeches.htm")],
    ),
    "ECB": BankShortcuts(
        "ECB",
        Shortcut("https://www.ecb.europa.eu/press/govcdec/mopo/html/index.en.html", "Monetary policy decision",
                 Finder("https://www.ecb.europa.eu/rss/press.html",
                        r"/press/pr/date/\d{4}/html/ecb\.mp(\d{6})[^\"'<\s]*\.en\.html")),
        Shortcut("https://www.ecb.europa.eu/press/projections/html/index.en.html", "Staff macroeconomic projections",
                 Finder("https://www.ecb.europa.eu/press/projections/html/index.en.html",
                        r"/press/projections/html/ecb\.projections(\d{6})[^\"'<\s]*\.en\.html"),
                 "Published in March, June, September and December."),
        [("Press conference", "https://www.ecb.europa.eu/press/press_conference/html/index.en.html"),
         ("Accounts (minutes)", "https://www.ecb.europa.eu/press/accounts/html/index.en.html")],
    ),
    "BOE": BankShortcuts(
        "BOE",
        Shortcut("https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes/monetary-policy-summary-and-minutes",
                 "Monetary Policy Summary",
                 Finder("https://www.bankofengland.co.uk/monetary-policy-summary-and-minutes/monetary-policy-summary-and-minutes",
                        r"/monetary-policy-summary-and-minutes/(\d{4})/([a-z]+)-\d{4}")),
        Shortcut("https://www.bankofengland.co.uk/monetary-policy-report/monetary-policy-report",
                 "Monetary Policy Report projections",
                 Finder("https://www.bankofengland.co.uk/monetary-policy-report/monetary-policy-report",
                        r"/monetary-policy-report/(\d{4})/([a-z]+)-\d{4}-monetary-policy-report"),
                 "Published in February, May, August and November."),
    ),
    "BOJ": BankShortcuts(
        "BOJ",
        Shortcut("https://www.boj.or.jp/en/mopo/mpmdeci/state_{year}/index.htm", "Statement on Monetary Policy",
                 Finder("https://www.boj.or.jp/en/mopo/mpmdeci/state_{year}/index.htm",
                        r"/en/mopo/mpmdeci/mpr_\d{4}/k(\d{6})a\.pdf")),
        Shortcut("https://www.boj.or.jp/en/mopo/outlook/index.htm", "Outlook Report (forecast table)",
                 Finder("https://www.boj.or.jp/en/mopo/outlook/index.htm", r"/en/mopo/outlook/gor(\d{4})a\.pdf"),
                 "The Bank's View (the 'a' file) holds the Policy Board's forecast table."),
    ),
    "SNB": BankShortcuts(
        "SNB",
        Shortcut("https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/decisions", "Monetary policy assessment",
                 Finder("https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/decisions",
                        r"/publications/communication/press-releases-restricted/pre_(\d{8})")),
        Shortcut("https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/decisions",
                 "Conditional inflation forecast",
                 Finder("https://www.snb.ch/en/the-snb/mandates-goals/monetary-policy/decisions",
                        r"/publications/communication/press-releases-restricted/pre_(\d{8})"),
                 "The forecast table is inside the assessment press release."),
        [("Quarterly Bulletin", "https://www.snb.ch/en/news-publications/economy/quarterly-bulletin")],
    ),
    "BOC": BankShortcuts(
        "BOC",
        Shortcut("https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
                 "Interest rate announcement",
                 Finder("https://www.bankofcanada.ca/core-functions/monetary-policy/key-interest-rate/",
                        r"/\d{4}/\d{2}/fad-press-release-(\d{4})-(\d{2})-(\d{2})/?")),
        Shortcut("https://www.bankofcanada.ca/publications/mpr/", "Monetary Policy Report projections",
                 Finder("https://www.bankofcanada.ca/publications/mpr/",
                        r"/publications/mpr/mpr-(\d{4})-(\d{2})-(\d{2})/?"),
                 "Published in January, April, July and October."),
    ),
    "RBA": BankShortcuts(
        "RBA",
        Shortcut("https://www.rba.gov.au/media-releases/{year}/", "Statement by the Monetary Policy Board",
                 Finder("https://www.rba.gov.au/media-releases/{year}/", r"/media-releases/\d{4}/mr-(\d{2})-(\d{2})\.html",
                        text=r"monetary policy (decision|board)")),
        Shortcut("https://www.rba.gov.au/publications/smp/", "Statement on Monetary Policy forecasts",
                 Finder("https://www.rba.gov.au/publications/smp/", r"/publications/smp/(\d{4})/([a-z]{3})/?$",
                        suffix="outlook.html"),
                 "The forecast table is in the Outlook chapter. Published in February, May, August and November."),
        [("Forecast archive", "https://www.rba.gov.au/publications/smp/forecasts-archive.html")],
    ),
    "RBNZ": BankShortcuts(
        "RBNZ",
        Shortcut("https://www.rbnz.govt.nz/monetary-policy/monetary-policy-decisions", "OCR decision",
                 Finder("https://www.rbnz.govt.nz/monetary-policy/monetary-policy-decisions",
                        r"/news-and-events/news/(\d{4})/(\d{2})/[a-z0-9-]*ocr[a-z0-9-]*", pick="max")),
        Shortcut("https://www.rbnz.govt.nz/monetary-policy/monetary-policy-decisions", "Monetary Policy Statement projections",
                 Finder("https://www.rbnz.govt.nz/monetary-policy/monetary-policy-decisions",
                        r"/monetary-policy/monetary-policy-statement/monetary-policy-statements/(\d{4})/[^/\"']+/"
                        r"monetary-policy-statement-([a-z]+)-\d{4}"),
                 "Published in February, May, August and November."),
    ),
    "SARB": BankShortcuts(
        "SARB",
        Shortcut("https://www.resbank.co.za/en/home/publications/statements/mpc-statements", "MPC statement",
                 Finder("https://www.resbank.co.za/en/home/publications/statements/mpc-statements",
                        r"/en/home/publications/statements/mpc-statements/\d{4}/[^\"'<\s]+", pick="first")),
        Shortcut("https://www.resbank.co.za/en/home/publications/statements/mpc-statements",
                 "MPC statement forecast table",
                 Finder("https://www.resbank.co.za/en/home/publications/statements/mpc-statements",
                        r"/en/home/publications/statements/mpc-statements/\d{4}/[^\"'<\s]+", pick="first"),
                 "The SARB's forecasts (inflation, growth) are set out in each MPC statement."),
        [("Monetary Policy Review", "https://www.resbank.co.za/en/home/publications/review/monetary-policy-review")],
    ),
    "BANXICO": BankShortcuts(
        "BANXICO",
        Shortcut("https://www.banxico.org.mx/publications-and-press/announcements-of-monetary-policy-decisions/"
                 "monetary-policy-announcements.html", "Monetary policy statement",
                 Finder("https://www.banxico.org.mx/publications-and-press/announcements-of-monetary-policy-decisions/"
                        "monetary-policy-announcements.html",
                        r"/publications-and-press/announcements-of-monetary-policy-decisions/(%7B|\{)[0-9A-Fa-f-]+(%7D|\})\.pdf",
                        pick="first")),
        Shortcut("https://www.banxico.org.mx/publications-and-press/announcements-of-monetary-policy-decisions/"
                 "monetary-policy-announcements.html", "Inflation forecast table",
                 Finder("https://www.banxico.org.mx/publications-and-press/announcements-of-monetary-policy-decisions/"
                        "monetary-policy-announcements.html",
                        r"/publications-and-press/announcements-of-monetary-policy-decisions/(%7B|\{)[0-9A-Fa-f-]+(%7D|\})\.pdf",
                        pick="first"),
                 "Each statement ends with Banxico's quarterly inflation forecast table. The full Quarterly Report "
                 "is under Publications on the Banxico site."),
    ),
    "PBOC": BankShortcuts(
        "PBOC",
        Shortcut("https://www.pbc.gov.cn/en/3688229/3688311/3688329/index.html", "Monetary Policy Committee meeting",
                 Finder("https://www.pbc.gov.cn/en/3688229/3688311/3688329/index.html",
                        r"/en/3688229/3688311/3688329/[0-9]+/index\.html", text=r"monetary policy committee",
                        pick="first")),
        Shortcut("https://www.pbc.gov.cn/en/3688229/3688353/3688356/index.html", "China Monetary Policy Report",
                 None, "The PBOC doesn't publish numeric forecasts; the report gives its outlook in words."),
    ),
}


def _fill(url: str, year: int) -> str:
    return url.replace("{year}", str(year))


def _key(m: re.Match) -> tuple:
    """Turn a link's captured date parts into something sortable ('2026', 'nov' -> (2026, 11))."""
    out = []
    for g in m.groups():
        if not g:
            continue
        g = g.lower()
        if g.isdigit():
            out.append(int(g))
        elif g[:3] in MONTHS:
            out.append(MONTHS[g[:3]])
    return tuple(out)


def find_links(page_html: str, base: str, finder: Finder) -> list[str]:
    """Every document link on the page that matches, newest first."""
    rx = re.compile(finder.href, re.I)
    text_rx = re.compile(finder.text, re.I) if finder.text else None
    seen: dict[str, tuple] = {}
    order: list[str] = []
    # links in <a href> tags (with their text) and bare links (RSS feeds, scripts)
    anchors = re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", page_html, re.I | re.S)
    candidates = [(h, re.sub(r"<[^>]+>", " ", t)) for h, t in anchors]
    if not text_rx:
        candidates += [(h, "") for h in re.findall(r"(?:https?://[^\s\"'<>]+|/[^\s\"'<>]+)", page_html)]
    for href, text in candidates:
        href = html.unescape(href.strip())
        m = rx.search(href)
        if not m:
            continue
        if text_rx and not text_rx.search(html.unescape(text)):
            continue
        full = urljoin(base, href[: m.end()] if finder.suffix else href)
        if not full.endswith("/") and finder.suffix:
            full += "/"
        full += finder.suffix
        if full not in seen:
            seen[full] = _key(m)
            order.append(full)
    if finder.pick == "max":
        order.sort(key=lambda u: seen[u], reverse=True)
    return order


def _short(exc: Exception) -> str:
    """A one-line reason a person can act on, instead of the raw network error."""
    msg = str(exc)
    m = re.search(r"\b(40[0-9]|429|5\d\d)\b", msg)
    if m and "Max retries" not in msg:
        return {"403": "the site refused the request (403)", "404": "the page has moved (404)",
                "429": "the site says too many requests (429)"}.get(m.group(1), f"the site returned {m.group(1)}")
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return "the site took too long to answer"
    return "the site couldn't be reached"


def latest_url(code: str, kind: str, today: date | None = None) -> str:
    """The newest official document for this bank and kind ('statement' or 'projections')."""
    bank = CATALOGUE.get(code.upper())
    if bank is None:
        raise LookupError(f"No shortcuts for {code}")
    sc = bank.statement if kind == "statement" else bank.projections
    if sc.finder is None:
        raise SourceUnavailable(f"{code} has no document to fetch automatically for {kind}. "
                                "Click Open, copy the document's link and paste it in the box.")
    year = (today or date.today()).year
    tried = []
    for y in (year, year - 1) if "{year}" in sc.finder.listing else (year,):
        listing = _fill(sc.finder.listing, y)
        tried.append(listing)
        try:
            page = http_get(listing, retries=1).text
        except SourceUnavailable as exc:
            raise SourceUnavailable(f"Couldn't read the official page: {_short(exc)}. Click Open, copy the "
                                    "newest document's link and paste it in the box.") from exc
        links = find_links(page, listing, sc.finder)
        if links:
            return links[0]
    raise SourceUnavailable("Couldn't spot the newest document on the official page (the bank may have changed "
                            "its website). Click Open, copy the document's link and paste it in the box.")


def serialize(code: str | None = None, today: date | None = None) -> list[dict]:
    year = (today or date.today()).year
    out = []
    for c, b in CATALOGUE.items():
        if code and c != code.upper():
            continue
        row = {"code": c, "extra": [{"label": l, "url": u} for l, u in b.extra]}
        for kind in ("statement", "projections"):
            sc: Shortcut = getattr(b, kind)
            row[kind] = {"page": _fill(sc.page, year), "label": sc.label, "auto": sc.finder is not None,
                         "note": sc.note}
        out.append(row)
    return out
