"""News tab: headlines from free feeds, tagged by currency, topic, tone and risk mood.

Sources (all free):
  - Central bank press releases (RSS): Fed, ECB, BoE, BoJ, RBA, BoC, RBNZ, SNB
  - FX news headlines (RSS): FXStreet, Investing.com forex news
  - Bank research (RSS): ING THINK (FX Daily, central bank previews and reviews, country outlooks)
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
    # news sites: several routes each, tried in order (the last is Google News' feed of that site's own headlines)
    ("fxstreet", "FXStreet", ("https://www.fxstreet.com/rss/news", "https://www.fxstreet.com/rss",
                              "https://news.google.com/rss/search?q=site:fxstreet.com+when:2d&hl=en-US&gl=US&ceid=US:en"),
     "news", []),
    ("investing", "Investing.com", "https://www.investing.com/rss/news_1.rss", "news", []),
    ("ing", "ING THINK", ("https://think.ing.com/rss/", "https://think.ing.com/rss/articles/",
                          "https://news.google.com/rss/search?q=site:think.ing.com+when:7d&hl=en-US&gl=US&ceid=US:en"),
     "news", []),  # ING's economics and FX research (free)
    # world news, kept only when the headline is geopolitical (wars, sanctions, tensions, ceasefires...)
    ("bbc_world", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "geopolitics", []),
    ("aljazeera", "Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", "geopolitics", []),
    ("geo_markets", "Geopolitics & markets (Google News)",
     "https://news.google.com/rss/search?q=(geopolitical+OR+sanctions+OR+ceasefire+OR+missile+OR+invasion)+markets+when:2d"
     "&hl=en-US&gl=US&ceid=US:en", "geopolitics", []),
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
    "Trade & politics": ["tariff", "trade", "election", "government", "shutdown", "budget", "fiscal", "debt"],
    "Geopolitics": [],  # matched with whole words: see GEO_WORDS
    "Commodities": ["gold", "silver", "oil", "crude", "opec", "copper", "commodit"],
}

GEO_WORDS = [r"wars?", r"warfare", r"invasion", r"invade[sd]?", r"missiles?", r"air ?strikes?", r"drone strikes?",
             r"military", r"troops", r"army", r"navy", r"ceasefire", r"truce", r"peace (talks|deal|plan)", r"sanctions?",
             r"embargo", r"blockade", r"nato", r"geopolitic\w*", r"conflict", r"hostilities", r"escalat\w+",
             r"de-?escalat\w+", r"nuclear (weapon|test|threat)\w*", r"coup", r"terror\w*", r"hostages?", r"shelling",
             r"bomb(ing|ed|s)?", r"attacks? on", r"strait of hormuz", r"red sea", r"houthis?", r"hezbollah", r"hamas",
             r"gaza", r"west bank", r"ukrain\w*", r"kremlin", r"putin", r"zelensk\w*", r"taiwan", r"south china sea",
             r"north korea\w*", r"pyongyang", r"tehran", r"iran\w*", r"israel\w*", r"syria\w*", r"yemen\w*",
             r"venezuela\w*", r"export controls?", r"rare earths?"]
_GEO = re.compile(r"(?<![a-z])(" + "|".join(GEO_WORDS) + r")(?![a-z])", re.I)

# hotspot: words that identify it, and what it usually means for currencies and commodities
HOTSPOTS = [
    ("Russia–Ukraine", r"ukrain\w*|russia\w*|kremlin|putin|zelensk\w*|moscow|kyiv|crimea|donbas",
     ["EUR", "CHF", "XAU", "OIL"],
     "Escalation hurts the euro (Europe's energy and growth) and lifts the Swiss franc, gold and gas/oil; peace talks do the reverse."),
    ("Middle East", r"israel\w*|gaza|hamas|hezbollah|lebanon|iran\w*|tehran|houthis?|red sea|yemen\w*|syria\w*|strait of hormuz|west bank",
     ["OIL", "XAU", "CAD", "JPY", "CHF"],
     "Escalation lifts oil (helping CAD and NOK), gold and the safe havens (JPY, CHF, USD); a threat to Hormuz or Red Sea shipping matters most."),
    ("US–China & Taiwan", r"taiwan|south china sea|export controls?|rare earths?|chip (curbs|ban)|beijing|xi jinping",
     ["CNY", "AUD", "NZD", "JPY", "USD"],
     "Tension weighs on the yuan and China-linked AUD/NZD and lifts the yen and dollar; deals and truces do the reverse."),
    ("Korean peninsula", r"north korea\w*|pyongyang|kim jong", ["JPY", "KRW", "XAU"],
     "Missile tests and threats bring brief safe-haven buying of the yen and gold."),
    ("Sanctions & trade wars", r"sanctions?|embargo|tariffs?|trade war", ["USD", "CNY", "MXN", "CAD", "EUR"],
     "New tariffs or sanctions hit the targeted country's currency (often MXN, CAD, CNY, EUR) and can lift the dollar."),
    ("Latin America", r"venezuela\w*|colombia\w*|cartels?", ["OIL", "MXN"],
     "Tension around Venezuela touches oil supply; US–Mexico security issues can weigh on the peso."),
]
_HOT = [(n, re.compile(r"(?<![a-z])(" + rx + r")(?![a-z])", re.I), c, why) for n, rx, c, why in HOTSPOTS]
ESCALATE = re.compile(r"(?<![a-z])(escalat\w+|attack\w*|strikes?|struck|invad\w+|missiles?|bomb\w*|shelling|retaliat\w+|"
                      r"threat\w*|mobili[sz]\w+|clash\w*|kill(ed|s|ing)|new sanctions|tensions? (rise|mount|flare)\w*|blockade)(?![a-z])", re.I)
CALM = re.compile(r"(?<![a-z])(ceasefire|truce|peace|talks|de-?escalat\w+|deal|agreement|withdraw\w*|lifts? sanctions|"
                  r"eases? sanctions|release[sd]? hostages|calm)(?![a-z])", re.I)


STALL = re.compile(r"(?<![a-z])(stall\w*|collaps\w+|fail\w*|break(s)? down|broke down|reject\w*|violat\w+|"
                   r"breach\w*|suspend\w*|walk(s|ed)? out)(?![a-z])", re.I)


def _direction(title: str) -> int:
    """+1 escalating, -1 calming, 0 unclear (e.g. "attack ... as talks stall" = escalating)."""
    e, c, st = ESCALATE.search(title), CALM.search(title), STALL.search(title)
    if st and (e or c):
        return 1
    if e and not c:
        return 1
    if c and not e:
        return -1
    if c and e:  # both: a deal / ceasefire outweighs; plain "talks" doesn't
        return -1 if c.group(0).lower() not in ("talks", "peace") else 1
    return 0


def is_geo(text: str) -> bool:
    return bool(_GEO.search(text or ""))


def geopolitics(arts: list) -> dict:
    """Hotspots in recent headlines: how many, escalating or calming, latest headlines, and what it means for markets."""
    spots = []
    for name, rx, ccys, why in _HOT:
        mine = [a for a in arts if is_geo(f"{a.title} {a.summary or ''}") and rx.search(f"{a.title} {a.summary or ''}")]
        if not mine:
            continue
        dirs = [_direction(a.title) for a in mine]
        esc, calm = dirs.count(1), dirs.count(-1)
        trend = "Escalating" if esc >= calm + 2 else "Calming" if calm >= esc + 2 else "Mixed"
        spots.append({"name": name, "articles": len(mine), "escalation": esc, "calming": calm, "trend": trend,
                      "affects": ccys, "impact": why, "latest": [_brief(a) for a in mine[:4]]})
    spots.sort(key=lambda x: -x["articles"])
    total = sum(1 for a in arts if is_geo(f"{a.title} {a.summary or ''}"))
    esc = sum(x["escalation"] for x in spots)
    calm = sum(x["calming"] for x in spots)
    return {"articles": total, "hotspots": spots,
            "lean": "Rising tension (supports safe havens: JPY, CHF, gold, USD)" if esc >= calm + 3 else
                    "Easing tension (supports risk currencies: AUD, NZD, EM)" if calm >= esc + 3 else
                    "No clear direction" if total else "Quiet"}


HAWKISH = [r"hawkish", r"rate hikes?", r"hikes? rates?",
           r"(raises?|raised|hikes?|hiked|lifts?|lifted) (the |its )?(repo|policy|benchmark|key|cash|bank|official|interest) rates?", r"hiking", r"raises? (interest )?rates?",
           r"raised (interest )?rates?", r"rate increase", r"tighten(ing|s|ed)?", r"higher for longer",
           r"sticky inflation", r"inflation (rises|rose|accelerat\w*|jumps|jumped|heats? up|surges?)",
           r"hot(ter)?(-than-expected)? (inflation|cpi)", r"stronger[- ]than[- ]expected", r"beats? (expectations|forecasts?)",
           r"strong (jobs|payrolls|data)", r"no (rush|hurry) to cut", r"fewer (rate )?cuts",
           r"(another|one more|further|a) hike", r"hikes? (in|at|this|next) ", r"push(es|ed)? back on (rate )?cuts"]
DOVISH = [r"dovish", r"rate cuts?", r"cuts? (interest )?rates?",
          r"(cuts?|lowers?|lowered|reduces?|reduced|trims?|trimmed) (the |its )?(repo|policy|benchmark|key|cash|bank|official|interest) rates?", r"cutting", r"eas(ing|es|ed) (policy|rates)",
          r"monetary easing", r"lowers? (interest )?rates?", r"lowered (interest )?rates?", r"rate reduction",
          r"slowdown", r"recession", r"contraction", r"weaker[- ]than[- ]expected", r"miss(es|ed)? (expectations|forecasts?)",
          r"disinflation", r"(inflation|prices) (cools?|cooled|eases?|eased|slows?|slowed|falls?|fell)",
          r"job losses", r"unemployment (rises|rose|jumps|climbs)", r"more (rate )?cuts", r"stimulus",
          r"(another|one more|further|a) cut", r"cuts? (in|at|this|next) ", r"door open to (easing|cuts?)", r"easing (cycle|bias)"]
RISK_OFF = [r"risk[- ]off", r"safe[- ]havens?", r"sell[- ]?off", r"plunges?", r"tumbles?", r"slumps?", r"crash",
            r"turmoil", r"\bwar\b", r"escalat\w+", r"fears?", r"panic", r"rout", r"flight to safety"]
RISK_ON = [r"risk[- ]on", r"rall(y|ies|ied)", r"record highs?", r"surges?", r"optimism", r"ceasefire",
           r"trade deal", r"deal reached", r"risk appetite", r"soars?"]
HIGH = [r"rate decision", r"interest rate decision", r"monetary policy statement", r"\bfomc\b", r"\bcpi\b",
        r"nonfarm|non-farm", r"\bgdp\b", r"emergency", r"press conference"]


# --------------------------------------------------------------------------- per-currency scoring
# A headline's wording is credited to the currency it is ABOUT, not to every currency it names:
#  - rate wording (hike / cut / hawkish / dovish) goes to the nearest central bank or currency named;
#  - move wording ("dollar gains", "gold slips", "EUR/USD falls") goes to that asset (a pair: base one way,
#    quote the other);
#  - gold and oil aren't hawkish or dovish: US rate wording counts against gold when gold is in the headline
#    (higher US rates / a stronger dollar usually weigh on gold).
BANK_WORDS = {"fed", "fomc", "federal reserve", "powell", "ecb", "lagarde", "boe", "bank of england", "bailey", "boj",
              "bank of japan", "ueda", "snb", "swiss national bank", "boc", "bank of canada", "macklem", "rba",
              "reserve bank of australia", "bullock", "rbnz", "reserve bank of new zealand", "sarb", "kganyago",
              "banxico", "pboc", "schlegel"}
COMMODITIES = {"XAU", "OIL"}
UP_WORDS = (r"gains?|gained|gaining|rises?|rose|rising|climbs?|climbed|climbing|jumps?|jumped|rall(?:y|ies|ied|ying)|"
            r"firms?|firmed|firming|strengthens?|strengthened|strengthening|surges?|surged|surging|advances?|advanced|"
            r"soars?|soared|rebounds?|rebounded|recovers?|recovered|extends? gains|hits? (?:a )?(?:record|fresh|new|\d+-\w+) high|"
            r"higher|stronger|bid|outperforms?|edges? up|ticks? up|holds? gains|gains? strength|picks? up")
DOWN_WORDS = (r"falls?|fell|falling|drops?|dropped|dropping|slips?|slipped|slipping|slides?|slid|sliding|weakens?|"
              r"weakened|weakening|declines?|declined|declining|tumbles?|tumbled|plunges?|plunged|sinks?|sank|"
              r"retreats?|retreated|slumps?|slumped|loses? ground|lost ground|extends? losses|hits? (?:a )?(?:fresh |new |\d+-\w+ )?low|"
              r"lower|weaker|offered|underperforms?|edges? (?:down|lower)|ticks? down|pares? gains|under pressure|sell-?off")
_UP = re.compile(r"^\W{0,3}(?:\w+\W+){0,2}?(" + UP_WORDS + r")\b", re.I)
_DOWN = re.compile(r"^\W{0,3}(?:\w+\W+){0,2}?(" + DOWN_WORDS + r")\b", re.I)


_OTHER_DOLLAR = re.compile(r"(canadian|australian|aussie|new zealand|kiwi|hong kong|singapore|taiwan(ese)?|nz|"
                           r"canada's|australia's)\s*$")
CURRENCY_WORDS["CAD"] = CURRENCY_WORDS["CAD"] + ["canadian dollar"]
CURRENCY_WORDS["AUD"] = CURRENCY_WORDS["AUD"] + ["australian dollar"]
CURRENCY_WORDS["NZD"] = CURRENCY_WORDS["NZD"] + ["new zealand dollar"]


def _mentions(low: str) -> list[tuple[int, int, str, bool]]:
    """(start, end, currency, is_central_bank) for each currency / bank word in the text."""
    out = []
    for c, words in CURRENCY_WORDS.items():
        for w in words:
            ww = w.strip()
            for m in re.finditer(r"(?<![a-z])" + re.escape(ww) + r"(?![a-z])", low):
                if ww == "dollar" and _OTHER_DOLLAR.search(low[max(0, m.start() - 16):m.start()]):
                    continue  # "Canadian dollar" is CAD, not USD
                out.append((m.start(), m.end(), c, ww in BANK_WORDS))
    return sorted(out)


_NEG_BEFORE = re.compile(r"(\bno\b|\bnot\b|\bnever\b|rules? out|ruled out|push(es|ed|ing)? back( on)?|pare[sd]?( back)?|"
                         r"scal(e|es|ed|ing) back|\bfewer\b|\bless\b|delay(s|ed|ing)?|\bagainst\b|rein(s|ed)? in|"
                         r"dial(s|led)? back|downplay(s|ed)?|reject(s|ed)?)[ '\-]+(\w+[ '\-]+){0,4}$")  # same clause only
_NEG_AFTER = re.compile(r"^\W*(\w+\W+){0,3}?(are |is |remain |remains |seem |seems |look |looks )?(some way off|a long way off|"
                        r"off the table|unlikely|not (imminent|coming|on the cards|expected)|ruled out|delayed|pushed back|"
                        r"on hold|premature|too early)")


def score_currencies(title: str, summary: str = "") -> dict[str, tuple[int, str]]:
    """+1 / -1 per asset this headline is about (+1 = supportive: hawkish or rising), with the reason."""
    text = f"{title}. {(summary or '')[:400]}"
    low = text.lower()
    ment = _mentions(low)
    pts: dict[str, list[tuple[int, str]]] = {}

    def add(c: str, v: int, why: str):
        pts.setdefault(c, []).append((v, why))

    # 1) moves: "<asset> gains", "EUR/USD falls"
    for m in PAIR_RE.finditer(text.upper()):
        rest = text[m.end():m.end() + 60]
        d = 1 if _UP.search(rest) else -1 if _DOWN.search(rest) else 0
        if d:
            add(m.group(1), d, f"{m.group(1)}/{m.group(2)} {'up' if d > 0 else 'down'}")
            add(m.group(2), -d, f"{m.group(1)}/{m.group(2)} {'up' if d > 0 else 'down'}")
    pair_spans = [(m.start(), m.end()) for m in PAIR_RE.finditer(text.upper())]
    for st, en, c, bank in ment:
        if bank or any(a <= st < b for a, b in pair_spans):
            continue
        rest = low[en:en + 60]
        d = 1 if _UP.search(rest) else -1 if _DOWN.search(rest) else 0
        if d:
            add(c, d, f"{'rising' if d > 0 else 'falling'} ({low[st:en].strip()})")
    # 2) rate wording -> the nearest central bank / currency (banks preferred), never gold or oil directly
    fiat = [x for x in ment if x[2] not in COMMODITIES]
    for rx, v0, word0 in ((_HAWK, 1, "hawkish"), (_DOVE, -1, "dovish")):
        other = _DOVE if v0 > 0 else _HAWK
        for m in rx.finditer(text):
            if not fiat:
                break
            v, word = v0, word0
            if _NEG_BEFORE.search(low[max(0, m.start() - 35):m.start()]) or _NEG_AFTER.search(low[m.end():m.end() + 40]):
                # "no rush to cut", "rate cuts are some way off", "rules out hikes" mean the opposite
                if any(abs(h.start() - m.start()) <= 25 for h in other.finditer(text)):
                    continue  # an opposite phrase right here ("no rush to cut") already counts it
                v, word = -v0, ("dovish" if v0 > 0 else "hawkish")
            sentence_start = max(low.rfind(". ", 0, m.start()), low.rfind("; ", 0, m.start())) + 1
            cands = [x for x in fiat if x[0] >= sentence_start] or fiat
            near = min(cands, key=lambda x: (0 if x[3] else 1, abs(x[0] - m.start())))
            add(near[2], v, f"{word} wording ({m.group(0).strip()}) about {near[2]}")
    # 3) gold reads US rates the other way round when gold is in the headline and has no move of its own
    if "USD" in pts and any(x[2] == "XAU" for x in ment) and "XAU" not in pts:
        us = sum(v for v, _ in pts["USD"] if "wording" in _)
        if us:
            add("XAU", -1 if us > 0 else 1, "US rate wording " + ("hawkish: weighs on gold" if us > 0 else "dovish: supports gold"))
    out = {}
    for c, lst in pts.items():
        net = sum(v for v, _ in lst)
        if net:
            out[c] = (1 if net > 0 else -1, "; ".join(w for _, w in lst))
    return out


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
    topics = [t for t, words in TOPICS.items() if words and any(w in low for w in words)]
    if is_geo(text):
        topics.append("Geopolitics")
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


# Some news sites turn away requests that don't look like a browser or feed reader, so feeds are fetched as one.
FEED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0 Safari/537.36 MacFundamentalIntelligence/1.0",
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}


def _clean_google(items: list[dict], site: str) -> list[dict]:
    """Google News titles end in " - Site name"; keep the publisher's own headline."""
    for it in items:
        t = it.get("title") or ""
        if " - " in t:
            it["title"] = t.rsplit(" - ", 1)[0].strip()
    return items


def fetch_rss(url) -> list[dict]:
    """One URL, or several routes tried in order until one returns headlines."""
    import requests

    urls = [url] if isinstance(url, str) else list(url)
    errors = []
    for u in urls:
        try:
            r = requests.get(u, headers=FEED_HEADERS, timeout=30)
            if r.status_code != 200:
                errors.append(f"{u.split('/')[2]} {r.status_code}")
                continue
            items = parse_rss(r.content)
        except Exception as exc:  # unreachable, or not a feed (e.g. a block page)
            errors.append(f"{u.split('/')[2]} {exc.__class__.__name__}")
            continue
        if items:
            return _clean_google(items, "") if "news.google.com" in u else items
        errors.append(f"{u.split('/')[2]} returned no headlines")
    raise SourceUnavailable("; ".join(errors))


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


FMP_NEWS = (("news/forex-latest", "forex"), ("news/general-latest", "general"), ("fmp-articles", "FMP articles"))


def fetch_fmp() -> tuple[list[dict], list[str]]:
    """FMP news (forex, general market, and FMP's own articles). Each list is tried separately; one not on your
    plan is noted and skipped. Shown under the source "FMP", with the original publisher at the start of the summary."""
    from zoneinfo import ZoneInfo

    import requests

    ny = ZoneInfo("America/New_York")  # FMP's timestamps are New York time
    out, missing = [], []
    for path, label in FMP_NEWS:
        try:
            r = requests.get(f"https://financialmodelingprep.com/stable/{path}",
                             params={"page": 0, "limit": 50, "apikey": settings.fmp_api_key}, timeout=30)
            body = r.json()
        except Exception as exc:
            missing.append(f"{label}: {exc.__class__.__name__}")
            continue
        if isinstance(body, dict) or r.status_code >= 400:
            msg = (body.get("Error Message") or body.get("message") or "") if isinstance(body, dict) else ""
            if r.status_code == 401 or ("invalid" in msg.lower() and "key" in msg.lower()):
                raise SourceUnavailable("FMP rejected the API key: check FMP_API_KEY in Railway")
            missing.append(f"{label}: {'not on your FMP plan' if r.status_code in (402, 403) or 'subscri' in msg.lower() or 'restricted' in msg.lower() else (msg or r.status_code)}")
            continue
        for it in body or []:
            if not isinstance(it, dict) or not it.get("title"):
                continue
            raw = str(it.get("publishedDate") or it.get("date") or "")
            try:
                pub = datetime.fromisoformat(raw.replace(" ", "T")[:19]).replace(tzinfo=ny).astimezone(timezone.utc)
            except ValueError:
                pub = None
            publisher = it.get("publisher") or it.get("site") or it.get("author") or ""
            text = clean(it.get("text") or it.get("content"))
            out.append({"title": clean(it["title"], 500), "link": it.get("url") or it.get("link") or "",
                        "summary": (f"{publisher}: {text}" if publisher and text else text or publisher) or None,
                        "source": "FMP", "published": pub})
    if not out and missing:
        raise SourceUnavailable("; ".join(missing))
    return out, missing


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
        if kind == "geopolitics" and not is_geo(f"{it['title']} {it.get('summary') or ''}"):
            continue  # world-news feeds: keep only the geopolitical headlines
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
    if settings.fmp_api_key:
        try:
            items, missing = fetch_fmp()
            added = store(db, items, "fmp", "FMP", "news", [])
            db.commit()
            status["fmp"] = {"name": "FMP", "ok": True, "added": added, "seen": len(items),
                             **({"note": "Skipped: " + "; ".join(missing)} if missing else {})}
            total += added
        except Exception as exc:
            db.rollback()
            status["fmp"] = {"name": "FMP", "ok": False, "error": f"{exc.__class__.__name__}: {exc}"[:200]}
    else:
        status["fmp"] = {"name": "FMP", "ok": False, "error": "Not set up: add FMP_API_KEY"}
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


def _brief(a: NewsArticle) -> dict:
    return {"id": a.id, "title": a.title, "url": a.url, "source": a.source_name, "kind": a.kind,
            "published_at": _aware(a.published_at).isoformat(), "tone": a.tone, "risk": a.risk}


_SCORE_CACHE: dict[int, dict] = {}


def scores_of(a: NewsArticle) -> dict[str, tuple[int, str]]:
    hit = _SCORE_CACHE.get(a.id)
    if hit is None:
        hit = score_currencies(a.title, a.summary or "")
        if len(_SCORE_CACHE) > 20000:
            _SCORE_CACHE.clear()
        _SCORE_CACHE[a.id] = hit
    return hit


def _scored(a: NewsArticle, c: str) -> dict:
    """How one headline counted for c: +1 supportive (hawkish / rising), -1 weighing (dovish / falling), 0 not about c."""
    sc = scores_of(a).get(c)
    pts = sc[0] if sc else 0
    why = sc[1] if sc else f"mentions {c}, but nothing in it is about {c} moving or its interest rates"
    return _brief(a) | {"points": pts, "why": why}


def row(a: NewsArticle) -> dict:
    return {"id": a.id, "title": a.title, "summary": a.summary, "url": a.url, "source": a.source_name,
            "feed": a.feed, "kind": a.kind, "published_at": _aware(a.published_at).isoformat(),
            "currencies": a.currencies or [], "tone_currencies": _toned(a), "topics": a.topics or [], "tone": a.tone, "risk": a.risk,
            "importance": a.importance}


def listing(db: Session, currency: str | None = None, topic: str | None = None, tone: str | None = None,
            kind: str | None = None, q: str | None = None, days: int = 7, limit: int = 150,
            source: str | None = None) -> dict:
    since = utcnow() - timedelta(days=days)
    arts = list(db.scalars(select(NewsArticle).where(NewsArticle.published_at >= since)
                           .order_by(NewsArticle.published_at.desc())))
    def ok(a: NewsArticle) -> bool:
        return ((not currency or currency.upper() in (a.currencies or []))
                and (not topic or topic in (a.topics or []) or (topic == "Geopolitics" and is_geo(f"{a.title} {a.summary or ''}")))
                and (not tone or (a.tone == tone if tone in ("hawkish", "dovish", "neutral") else a.risk == tone))
                and (not kind or a.kind == kind) and (not source or a.source_name == source)
                and (not q or q.lower() in f"{a.title} {a.summary or ''}".lower()))
    shown = [a for a in arts if ok(a)]
    # news tone per currency over the last 3 days: hawkish +1, dovish -1
    recent = [a for a in arts if _aware(a.published_at) >= utcnow() - timedelta(days=3)]
    tone_by = {}
    for c in ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN", "CNY", "XAU", "OIL"]:
        mine = [a for a in recent if c in (a.currencies or []) or c in scores_of(a)]
        vals = [scores_of(a).get(c, (0, ""))[0] for a in mine]
        hk, dv = vals.count(1), vals.count(-1)
        up, down = ("Bullish", "Bearish") if c in COMMODITIES else ("Hawkish", "Dovish")
        tone_by[c] = {"articles": len(mine), "hawkish": hk, "dovish": dv, "net": hk - dv,
                      "lean": up if hk - dv >= 2 else down if dv - hk >= 2 else "Balanced" if mine else "Quiet",
                      "labels": [up, down],
                      "breakdown": [_scored(a, c) for a in mine]}
    ro = sum(a.risk == "risk_off" for a in recent)
    rn = sum(a.risk == "risk_on" for a in recent)
    risk_items = [_brief(a) | {"points": 1 if a.risk == "risk_on" else -1} for a in recent if a.risk]
    src = db.scalar(select(Source).where(Source.key == "news"))
    cfg = (src.config or {}) if src else {}
    counts: dict[tuple[str, str], int] = {}
    for a in arts:  # every site in the period, so you can pick one (central banks first, then by number of articles)
        counts[(a.source_name, a.kind)] = counts.get((a.source_name, a.kind), 0) + 1
    sources = [{"name": n, "kind": k, "count": c}
               for (n, k), c in sorted(counts.items(), key=lambda x: ({"central_bank": 0, "news": 1}.get(x[0][1], 2), -x[1], x[0][0]))]
    return {"articles": [row(a) for a in shown[:limit]], "total": len(shown), "tone": tone_by, "sources": sources,
            "risk": {"risk_on": rn, "risk_off": ro, "items": risk_items, "lean": "Risk-off" if ro - rn >= 3 else "Risk-on" if rn - ro >= 3 else "Mixed"},
            "topics": list(TOPICS), "feeds": cfg.get("feeds", {}), "last_run": cfg.get("last_run"),
            "geopolitics": geopolitics(recent)}


def tone_cells(db: Session, days: int = 3) -> dict[str, int]:
    """Per currency: +1 if the last few days' news leans hawkish (2+ more hawkish than dovish headlines),
    -1 if it leans dovish, 0 if balanced. Used as the News tone column on Top setups."""
    since = utcnow() - timedelta(days=days)
    arts = list(db.scalars(select(NewsArticle).where(NewsArticle.published_at >= since)))
    out: dict[str, int] = {}
    for a in arts:
        for c in a.currencies or []:
            out.setdefault(c, 0)
        for c, (v, _) in scores_of(a).items():
            out[c] = out.get(c, 0) + v
    risk = sum(1 if a.risk == "risk_on" else -1 if a.risk == "risk_off" else 0 for a in arts)
    cells = {c: (1 if n >= 2 else -1 if n <= -2 else 0) for c, n in out.items()}
    cells["_risk"] = 1 if risk >= 3 else -1 if risk <= -3 else 0
    return cells
