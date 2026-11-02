"""Press conference analysis. Pure functions: transcript text in, analysis out.

  split_turns   who said what (speaker labels like 'CHAIR POWELL.', 'Lagarde:', 'Question:')
  analyse       opening remarks vs Q&A tone, answer-by-answer tone, forward-guidance phrases,
                topics and their lean, most hawkish / dovish quotes
"""
from __future__ import annotations

import math
import re

from app.analytics import statement as sx

CHAIRS = ["powell", "lagarde", "bailey", "ueda", "bullock", "macklem", "schlegel", "kganyago", "hawkesby", "breman",
          "orr", "rodríguez", "rodriguez", "heath", "chair", "president", "governor"]
MODERATORS = ["michelle smith", "moderator", "host", "spokesperson", "press officer"]

# forward-guidance phrases: (phrase, lean) lean +1 hawkish, -1 dovish, 0 = guidance to note
PHRASES: list[tuple[str, int]] = [
    ("meeting by meeting", 0), ("meeting-by-meeting", 0), ("data dependent", 0), ("data-dependent", 0),
    ("not a foregone conclusion", 1), ("far from", 1), ("no rush", 1), ("in no hurry", 1), ("not in a hurry", 1),
    ("not on a preset course", 0), ("well positioned", 0), ("good place", 0), ("wait and see", 0),
    ("further tightening", 1), ("additional firming", 1), ("prepared to raise", 1), ("prepared to tighten", 1),
    ("rate hike", 1), ("raise rates", 1), ("higher for longer", 1), ("restrictive for longer", 1),
    ("inflation remains elevated", 1), ("upside risks to inflation", 1), ("sticky", 1), ("persistent", 1),
    ("not yet confident", 1), ("vigilant", 1), ("strong labour market", 1), ("strong labor market", 1),
    ("rate cut", -1), ("cut rates", -1), ("further easing", -1), ("lower rates", -1), ("less restrictive", -1),
    ("downside risks", -1), ("labour market is cooling", -1), ("labor market is cooling", -1),
    ("disinflation", -1), ("inflation is coming down", -1), ("confident that inflation", -1),
    ("insurance cut", -1), ("risks have shifted", -1), ("weakening", -1), ("slowdown", -1),
]
TOPICS = {
    "Inflation": ["inflation", "prices", "price pressures", "cpi", "pce", "wages", "core"],
    "Jobs": ["labor market", "labour market", "employment", "unemployment", "jobs", "payroll", "hiring"],
    "Growth": ["growth", "gdp", "activity", "demand", "spending", "recession", "economy"],
    "Rates & policy path": ["rate", "rates", "policy", "cut", "hike", "easing", "tightening", "path", "neutral"],
    "Trade & tariffs": ["tariff", "trade", "exports", "imports"],
    "Financial conditions": ["financial conditions", "markets", "yields", "balance sheet", "liquidity", "banks"],
    "Currency": ["dollar", "euro", "yen", "sterling", "exchange rate", "currency", "franc"],
}
# speaker labels: ALL-CAPS names ending in a full stop (Fed style: 'CHAIR POWELL.') or a name then a colon
# ('Christine Lagarde:', 'Question:'), at the start of a line or after a sentence end
_SPK = re.compile(r"(?:^|(?<=[.?!\"”]\s))\s*(?:\*\*)?((?:[A-Z][A-Z.'\-]+(?: [A-Z][A-Z.'\-]+){0,3})(?=\.\s)|"
                  r"(?:[A-Z][A-Za-zÀ-ÿ.'\-]+(?: [A-Z][A-Za-zÀ-ÿ.'\-]+){0,3})(?=:\s))(?:\*\*)?[.:]\s+", re.M)


def _clean(text: str) -> str:
    t = text.replace("\r", "")
    t = re.sub(r"Page \d+ of \d+", " ", t)
    t = re.sub(r"\n\s*\d+\s*\n", "\n", t)
    return t


def _role(label: str) -> str:
    low = label.lower().strip()
    if low in ("question", "q", "journalist", "reporter") or low.startswith("question"):
        return "q"
    if low in ("answer", "a"):
        return "chair"
    if any(m in low for m in MODERATORS):
        return "mod"
    if any(c in low for c in CHAIRS):
        return "chair"
    return "q"


def split_turns(text: str) -> list[dict]:
    """[{speaker, role, text}] in order. Without speaker labels the whole text is one chair turn."""
    t = _clean(text)
    marks = [m for m in _SPK.finditer(t) if len(m.group(1).split()) <= 4 and len(m.group(1)) >= 2
             and m.group(1).upper() not in ("U.S", "U.K", "I", "A", "OK", "Q.E")]
    if len(marks) < 2:
        return [{"speaker": "Chair", "role": "chair", "text": re.sub(r"\s+", " ", t).strip()}]
    turns = []
    head = t[:marks[0].start()].strip()
    if len(head) > 200:
        turns.append({"speaker": "Opening", "role": "chair", "text": re.sub(r"\s+", " ", head)})
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(t)
        body = re.sub(r"\s+", " ", t[m.end():end]).strip()
        if body:
            turns.append({"speaker": m.group(1).strip(), "role": _role(m.group(1)), "text": body})
    return turns


def tone100(text: str) -> float:
    return sx.statement_tone(text) if text.strip() else 0.0


def analyse(text: str) -> dict:
    turns = split_turns(text)
    first_q = next((i for i, t in enumerate(turns) if t["role"] == "q"), len(turns))
    opening = " ".join(t["text"] for t in turns[:first_q] if t["role"] == "chair")
    qa_pairs: list[dict] = []
    for i, t in enumerate(turns[first_q:], start=first_q):
        if t["role"] != "q":
            continue
        ans = []
        for u in turns[i + 1:]:
            if u["role"] == "q":
                break
            if u["role"] == "chair":
                ans.append(u["text"])
        if ans:
            a = " ".join(ans)
            qa_pairs.append({"who": t["speaker"], "question": t["text"][:600], "answer": a[:4000],
                             "tone": tone100(a), "topics": _topics_of(t["text"] + " " + a)})
    answers = " ".join(p["answer"] for p in qa_pairs)
    chair_all = " ".join(t["text"] for t in turns if t["role"] == "chair")
    t_open, t_qa = tone100(opening), (tone100(answers) if answers else None)
    overall = round(0.4 * t_open + 0.6 * t_qa, 1) if t_qa is not None and opening else tone100(chair_all)
    low = " " + re.sub(r"\s+", " ", chair_all.lower()) + " "
    phrases = []
    for ph, lean in PHRASES:
        n = len(re.findall(r"(?<![a-z])" + re.escape(ph) + r"(?![a-z])", low))
        if n:
            i = low.find(ph)
            phrases.append({"phrase": ph, "lean": lean, "count": n,
                            "context": low[max(0, i - 90): i + len(ph) + 90].strip()})
    phrases.sort(key=lambda p: (-abs(p["lean"]), -p["count"]))
    sents = sx.split_sentences(chair_all)
    scored = [(sx.tone(s)[0], s) for s in sents if 40 <= len(s) <= 400]
    hawk = [s for sc, s in sorted(scored, key=lambda x: -x[0]) if sc > 0][:3]
    dove = [s for sc, s in sorted(scored, key=lambda x: x[0]) if sc < 0][:3]
    topics = []
    total = max(1, len(sents))
    for name, kws in TOPICS.items():
        ss = [s for s in sents if any(re.search(r"(?<![a-z])" + re.escape(k), s.lower()) for k in kws)]
        if ss:
            sc = sum(sx.tone(s)[0] for s in ss)
            topics.append({"topic": name, "share": round(100 * len(ss) / total), "lean": round(100 * math.tanh(sc / 6), 0)})
    topics.sort(key=lambda x: -x["share"])
    return {"tone": overall, "opening_tone": t_open if opening else None, "qa_tone": t_qa, "questions": len(qa_pairs),
            "qa": qa_pairs, "phrases": phrases[:20], "topics": topics, "hawkish_quotes": hawk, "dovish_quotes": dove,
            "label": label(overall), "has_qa": bool(qa_pairs)}


def _topics_of(text: str) -> list[str]:
    low = text.lower()
    return [n for n, kws in TOPICS.items() if any(re.search(r"(?<![a-z])" + re.escape(k), low) for k in kws)][:3]


def label(t: float | None) -> str:
    if t is None:
        return "—"
    return ("Hawkish" if t >= 25 else "Leaning hawkish" if t >= 8 else "Dovish" if t <= -25
            else "Leaning dovish" if t <= -8 else "Balanced")


def compare_phrases(prev: list[dict], cur: list[dict]) -> dict:
    a, b = {p["phrase"] for p in prev}, {p["phrase"] for p in cur}
    return {"added": sorted(b - a), "dropped": sorted(a - b)}
