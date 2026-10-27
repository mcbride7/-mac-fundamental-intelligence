"""News tab: headlines from free feeds, tagged by currency, topic, tone and risk mood.

Sources (all free):
  - Central bank press releases (RSS): Fed, ECB, BoE, BoJ, RBA, BoC, RBNZ, SNB
  - FX news headlines (RSS): FXStreet, Investing.com forex news
  - Finnhub forex news (if FINNHUB_API_KEY is set)
Only the headline, a short summary and the link are kept; the full article stays on the publisher's site.
A feed that fails is skipped (and listed as failed on the page) so one broken feed never stops the rest.

Tagging is by keywords, so it is a quick guide rather than a judgement:
  tone     hawkish (hikes, tightening, hot inflation, strong data) / dovish (cuts, easing, weak data)
  risk     risk-on (rally, record highs, deal) / risk-off (sell-off, safe havens, war, fears)
"""
from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import utcnow
from app.ingestion.base import SourceUnavailable, http_get
from app.models import NewsArticle, Source

KEEP_DAYS = 30

# key, name, url, kind, currencies always attached
RSS_FEEDS = [
    ("fed", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "central_bank", ["USD"]),
    ("ecb", "European Central Bank", "https://www.ecb.europa.eu/rss/press.html", "central_bank", ["EUR"]),
    ("boe", "Bank of England", "https://www.bankofengland.co.uk/rss/news", "central_bank", ["GBP"]),
    ("boj", "Bank of Japan", "https://www.boj.or.jp/en/rss/whatsnew.xml", "central_bank", ["JPY"]),
    ("rba", "Reserve Bank of Australia", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml", "central_bank",
     ["AUD"]),
    ("boc", "Bank of Canada", "https://www.bankofcanada.ca/content_type/press-releases/feed/", "central_bank",
     ["CAD"]),
    ("rbnz", "Reserve Bank of New Zealand", "https://www.rbnz.govt.nz/feeds/news", "central_bank", ["NZD"]),
    ("snb", "Swiss National Bank", "https://www.snb.ch/public/en/rss/pressrel", "central_bank", ["CHF"]),
    ("fxstreet", "FXStreet", "https://www.fxstreet.com/rss/news", "news", []),
    ("investing", "Investing.com", "https://www.investing.com/rss/news_1.rss", "news", []),
]

CURRENCY_WORDS = {
    "USD": ["fed", "fomc", "federal reserve", "powell", "dollar", "greenback", "u.s.", "us ", "united states",
            "treasury", "treasuries", "nonfarm", "non-farm", "payrolls", "dxy", "wall street", "white house",
            "trump"],
    "EUR": ["ecb", "lagarde", "euro", "eurozone", "euro area", "germany", "german", "france", "french",
            "italy", "bund", "eu "],
    "GBP": ["boe", "bank of england", "bailey", "pound", "sterling", "uk ", "u.k.", "britain", "british",
            "gilt", "reeves", "cable"],
    "JPY": ["boj", "bank of japan", "ueda", "yen", "japan", "japanese", "jgb", "takaichi"],
    "CHF": ["snb", "swiss national bank", "swiss", "franc", "switzerland", "schlegel"],
    "CAD": ["boc", "bank of canada", "macklem", "loonie", "canada", "canadian"],
    "AUD": ["rba", "reserve bank of australia", "bullock", "aussie", "australia", "australian"],
    "NZD": ["rbnz", "reserve bank of new zealand", "kiwi", "new zealand"],
    "ZAR": ["sarb", "rand", "south africa", "kganyago"],
    "MXN": ["banxico", "peso", "mexico", "mexican"],
    "CNY": ["pboc", "yuan", "renminbi", "china", "chinese", "beijing"],
    "XAU": ["gold", "bullion", "xau"],
    "OIL": ["oil", "crude", "opec", "brent", "wti"],
}
PAIR_RE = re.compile(r"\b(USD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|ZAR|MXN|CNY|XAU)\s*/?\s*(USD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|ZAR|MXN|CNY)\b")

TOPICS = {
    "Central banks": ["central bank", "fed ", "fed's", "powell", "lagarde", "bailey", "ueda", "macklem",
                      "bullock", "rate decision", "interest rate", "monetary policy", "fomc", "ecb", "boe",
                      "boj", "rba", "rbnz", "snb", "boc", "banxico", "sarb", "pboc", "governor", "policymaker",
                      "minutes", "press conference", "rate cut", "rate hike"],
    "Inflation": ["inflation", "cpi", "pce", "hicp", "prices", "ppi", "deflation", "disinflation"],
    "Jobs": ["jobs", "payrolls", "unemployment", "employment", "jobless", "labor market", "labour market",
             "wages", "earnings"],
    "Growth": ["gdp", "growth", "recession", "pmi", "retail sales", "manufacturing", "services sector",
               "consumer confidence", "sentiment", "output"],
    "Trade & politics": ["tariff", "trade", "election", "government", "shutdown", "sanction", "war", "geopolit",
                         "budget", "fiscal", "debt"],
    "Commodities": ["gold", "silver", "oil", "crude", "opec", "copper", "commodit"],
}

HAWKISH = [r"hawkish", r"rate hikes?", r"hikes? rates?", r"hiking", r"raises? (interest )?rates?",
           r"raised (interest )?rates?", r"rate increase", r"tighten(ing|s|ed)?", r"higher for longer",
           r"sticky inflation", r"inflation (rises|rose|accelerat\w*|jumps|jumped|heats? up|surges?)",
           r"hot(ter)?(-than-expected)? (inflation|cpi)", r"stronger[- ]than[- ]expected", r"beats? (expectations|forecasts?)",
           r"strong (jobs|payrolls|data)", r"no (rush|hurry) to cut", r"fewer (rate )?cuts"]
DOVISH = [r"dovish", r"rate cuts?", r"cuts? (interest )?rates?", r"cutting", r"eas(ing|es|ed) (policy|rates)",
          r"monetary easing", r"lowers? (interest )?rates?", r"lowered (interest )?rates?", r"rate reduction",
          r"slowdown", r"recession", r"contraction", r"weaker[- ]than[- ]expected", r"miss(es|ed)? (expectations|forecasts?)",
          r"disinflation", r"(inflation|prices) (cools?|cooled|eases?|eased|slows?|slowed|falls?|fell)",
          r"job losses", r"unemployment (rises|rose|jumps|climbs)", r"more (rate )?cuts", r"stimulus"]
RISK_OFF = [r"risk[- ]off", r"safe[- ]havens?", r"sell[- ]?off", r"plunges?", r"tumbles?", r"slumps?", r"crash",
            r"turmoil", r"\bwar\b", r"escalat\w+", r"fears?", r"panic", r"rout", r"flight to safety"]
RISK_ON = [r"risk[- ]on", r"rall(y|ies|ied)", r"record highs?", r"surges?", r"optimism", r"ceasefire",
           r"trade deal", r"deal reached", r"risk appetite", r"soars?"]
HIGH = [r"rate decision", r"interest rate decision", r"monetary policy statement", r"\bfomc\b", r"\bcpi\b",
        r"nonfarm|non-farm", r"\bgdp\b", r"emergency", r"press conference"]


def _rx(words: list[str]) -> re.Pattern:
    return re.compile(r"\b(" + "|".join(words) + r")", re.I)


_HAWK, _DOVE, _ROFF, _RON, _HIGH = _rx(HAWKISH), _rx(DOVISH), _rx(RISK_OFF), _rx(RISK_ON), _rx(HIGH)


def clean(text: str | None, limit: int = 600) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= limit else t[: limit - 1].rsplit(" ", 1)[0] + "…"


def classify(title: str, summary: str = "", base_ccys: list[str] | None = None) -> dict:
    text = f"{title}. {summary}"
    low = f" {text.lower()} "
    named = list(base_ccys or [])
    for c, words in CURRENCY_WORDS.items():
        if c not in named and any(re.search(r"(?<![a-z])" + re.escape(w.strip()) + r"(?![a-z])", low)
                                 for w in words):
            named.append(c)
    ccys = list(named)
    for a, b in PAIR_RE.findall(text.upper()):
        for c in (a, b):
            if c not in ccys:
                ccys.append(c)
    topics = [t for t, words in TOPICS.items() if any(w in low for w in words)]
    h, d = len(_HAWK.findall(text)), len(_DOVE.findall(text))
    tone = "hawkish" if h > d else "dovish" if d > h else "neutral"
    ro, rn = len(_ROFF.findall(text)), len(_RON.findall(text))
    risk = "risk_off" if ro > rn else "risk_on" if rn > ro else None
    importance = "high" if _HIGH.search(text) else "normal"
    return {"currencies": ccys, "tone_currencies": named, "topics": topics, "tone": tone, "risk": risk,
            "importance": importance}


def uid_of(url: str | None, title: str) -> str:
    return hashlib.sha1((url or title).strip().lower().encode()).hexdigest()


def _aware(t: datetime | None) -> datetime:
    if t is None:
        return utcnow()
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def parse_rss(xml_bytes: bytes) -> list[dict]:
    """RSS or Atom -> [{title, link, published, summary}]."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    root = ET.fromstring(xml_bytes)
    out = []
    for it in root.iter():
        if it.tag.split("}")[-1] not in ("item", "entry"):
            continue
        get = {c.tag.split("}")[-1]: c for c in it}
        title = clean(get["title"].text if "title" in get else "", 500)
        link_el = get.get("link")
        link = ((link_el.text or link_el.attrib.get("href", "")) if link_el is not None else "").strip()
        # (an XML element with no children is falsy, so pick the first tag that exists, not `or`)
        summ_el = next((get[k] for k in ("description", "summary", "content") if k in get), None)
        date_el = next((get[k] for k in ("pubDate", "published", "updated", "date") if k in get), None)
        pub = None
        if date_el is not None and date_el.text:
            try:
                pub = parsedate_to_datetime(date_el.text.strip())
            except (TypeError, ValueError):
                try:
                    pub = datetime.fromisoformat(date_el.text.strip().replace("Z", "+00:00"))
                except ValueError:
                    pub = None
        if title:
            out.append({"title": title, "link": link, "published": pub,
                        "summary": clean(summ_el.text if summ_el is not None else "")})
    return out


def fetch_rss(url: str) -> list[dict]:
    return parse_rss(http_get(url, retries=1).content)


def fetch_finnhub() -> list[dict]:
    out = []
    for cat in ("forex", "general"):
        r = http_get("https://finnhub.io/api/v1/news", {"category": cat, "token": settings.finnhub_api_key}, retries=1)
        for it in r.json() or []:
            if not it.get("headline"):
                continue
            out.append({"title": clean(it["headline"], 500), "link": it.get("url") or "",
                        "summary": clean(it.get("summary")), "source": it.get("source") or "Finnhub",
                        "published": datetime.fromtimestamp(it["datetime"], tz=timezone.utc) if it.get("datetime") else None})
    return out


def store(db: Session, items: list[dict], feed: str, source_name: str, kind: str, base_ccys: list[str]) -> int:
    cutoff = utcnow() - timedelta(days=KEEP_DAYS)
    seen = set(db.scalars(select(NewsArticle.uid).where(NewsArticle.feed == feed)))
    titles = {t.lower() for t in db.scalars(select(NewsArticle.title).where(NewsArticle.published_at >= cutoff))}
    n = 0
    for it in items:
        pub = _aware(it.get("published"))
        uid = uid_of(it.get("link"), it["title"])
        if pub < cutoff or uid in seen or it["title"].lower() in titles:
            continue
        tags = classify(it["title"], it.get("summary") or "", base_ccys)
        if kind == "central_bank":
            tags["importance"] = "high" if tags["importance"] == "high" or "Central banks" in tags["topics"] else "normal"
        db.add(NewsArticle(uid=uid, title=it["title"], summary=it.get("summary") or None, url=it.get("link") or None,
                           source_name=it.get("source") or source_name, feed=feed, kind=kind, published_at=pub, **tags))
        seen.add(uid)
        titles.add(it["title"].lower())
        n += 1
    return n


def run_news(db: Session, src: Source) -> int:
    status: dict[str, dict] = {}
    total = 0
    feeds = list(RSS_FEEDS)
    for key, name, url, kind, ccys in feeds:
        try:
            items = fetch_rss(url)
            added = store(db, items, key, name, kind, ccys)
            db.commit()
            status[key] = {"name": name, "ok": True, "added": added, "seen": len(items)}
            total += added
        except Exception as exc:  # one broken feed never stops the others
            db.rollback()
            status[key] = {"name": name, "ok": False, "error": f"{exc.__class__.__name__}: {exc}"[:200]}
    if settings.finnhub_api_key:
        try:
            items = fetch_finnhub()
            added = store(db, items, "finnhub", "Finnhub", "news", [])
            db.commit()
            status["finnhub"] = {"name": "Finnhub", "ok": True, "added": added, "seen": len(items)}
            total += added
        except Exception as exc:
            db.rollback()
            status["finnhub"] = {"name": "Finnhub", "ok": False, "error": f"{exc.__class__.__name__}: {exc}"[:200]}
    else:
        status["finnhub"] = {"name": "Finnhub", "ok": False, "error": "Not set up: add FINNHUB_API_KEY (free key)"}
    db.execute(delete(NewsArticle).where(NewsArticle.published_at < utcnow() - timedelta(days=KEEP_DAYS)))
    src = db.get(Source, src.id)
    src.config = {**(src.config or {}), "feeds": status, "last_run": utcnow().isoformat()}
    db.commit()
    if not any(s.get("ok") for s in status.values()):
        raise SourceUnavailable("No news feed could be reached: " + "; ".join(
            f"{s['name']}: {s.get('error')}" for s in status.values())[:800])
    return total


def _toned(a: NewsArticle) -> list[str]:
    return a.tone_currencies if a.tone_currencies is not None else (a.currencies or [])


def row(a: NewsArticle) -> dict:
    return {"id": a.id, "title": a.title, "summary": a.summary, "url": a.url, "source": a.source_name,
            "feed": a.feed, "kind": a.kind, "published_at": _aware(a.published_at).isoformat(),
            "currencies": a.currencies or [], "tone_currencies": _toned(a), "topics": a.topics or [], "tone": a.tone, "risk": a.risk,
            "importance": a.importance}


def listing(db: Session, currency: str | None = None, topic: str | None = None, tone: str | None = None,
            kind: str | None = None, q: str | None = None, days: int = 7, limit: int = 150) -> dict:
    since = utcnow() - timedelta(days=days)
    arts = list(db.scalars(select(NewsArticle).where(NewsArticle.published_at >= since)
                           .order_by(NewsArticle.published_at.desc())))
    def ok(a: NewsArticle) -> bool:
        return ((not currency or currency.upper() in (a.currencies or [])) and (not topic or topic in (a.topics or []))
                and (not tone or (a.tone == tone if tone in ("hawkish", "dovish", "neutral") else a.risk == tone))
                and (not kind or a.kind == kind) and (not q or q.lower() in f"{a.title} {a.summary or ''}".lower()))
    shown = [a for a in arts if ok(a)]
    # news tone per currency over the last 3 days: hawkish +1, dovish -1
    recent = [a for a in arts if _aware(a.published_at) >= utcnow() - timedelta(days=3)]
    tone_by = {}
    for c in ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN", "CNY", "XAU", "OIL"]:
        mine = [a for a in recent if c in (a.currencies or [])]
        toned = [a for a in mine if c in _toned(a)]
        hk, dv = sum(a.tone == "hawkish" for a in toned), sum(a.tone == "dovish" for a in toned)
        tone_by[c] = {"articles": len(mine), "hawkish": hk, "dovish": dv, "net": hk - dv,
                      "lean": "Hawkish" if hk - dv >= 2 else "Dovish" if dv - hk >= 2 else "Balanced" if mine else "Quiet"}
    ro = sum(a.risk == "risk_off" for a in recent)
    rn = sum(a.risk == "risk_on" for a in recent)
    src = db.scalar(select(Source).where(Source.key == "news"))
    cfg = (src.config or {}) if src else {}
    return {"articles": [row(a) for a in shown[:limit]], "total": len(shown), "tone": tone_by,
            "risk": {"risk_on": rn, "risk_off": ro, "lean": "Risk-off" if ro - rn >= 3 else "Risk-on" if rn - ro >= 3 else "Mixed"},
            "topics": list(TOPICS), "feeds": cfg.get("feeds", {}), "last_run": cfg.get("last_run")}


def tone_cells(db: Session, days: int = 3) -> dict[str, int]:
    """Per currency: +1 if the last few days' news leans hawkish (2+ more hawkish than dovish headlines),
    -1 if it leans dovish, 0 if balanced. Used as the News tone column on Top setups."""
    since = utcnow() - timedelta(days=days)
    arts = list(db.scalars(select(NewsArticle).where(NewsArticle.published_at >= since)))
    out: dict[str, int] = {}
    for a in arts:
        for c in a.currencies or []:
            out.setdefault(c, 0)
            if c not in _toned(a):
                continue
            out[c] += 1 if a.tone == "hawkish" else -1 if a.tone == "dovish" else 0
    risk = sum(1 if a.risk == "risk_on" else -1 if a.risk == "risk_off" else 0 for a in arts)
    cells = {c: (1 if n >= 2 else -1 if n <= -2 else 0) for c, n in out.items()}
    cells["_risk"] = 1 if risk >= 3 else -1 if risk <= -3 else 0
    return cells
