"""Central-bank statement comparison (Sections 7-9).

1. Split both statements into sentences.
2. Align them (unchanged / modified / added / removed) with difflib.
3. Word-level diff for modified sentences.
4. Classify each sentence into policy-language categories.
5. Score hawkish/dovish tone with a phrase lexicon; the change in tone gives
   the direction (Hawkish / Dovish / Neutral / Mixed) and importance.

Deterministic and explainable. An LLM can add richer interpretation on top
(see engines/cb_engine.py) but the classification never depends on it."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

CATEGORIES: dict[str, list[str]] = {
    "Inflation": ["inflation", "price pressures", "prices", "core inflation", "inflation expectations", "cpi",
                  "pce", "hicp", "price stability", "disinflation"],
    "Employment": ["employment", "unemployment", "labor market", "labour market", "wages", "wage", "job",
                   "payroll", "labor demand", "labour demand"],
    "Growth": ["gdp", "economic activity", "growth", "consumer spending", "business investment",
               "output", "expanding", "expansion", "demand"],
    "Monetary Policy": ["target range", "federal funds rate", "policy rate", "interest rate", "restrictive",
                        "accommodat", "bank rate", "deposit facility", "repo rate", "cash rate", "normaliz",
                        "normalis", "basis point", "key ecb interest rates"],
    "Forward Guidance": ["future", "additional adjustments", "coming meetings", "data-dependent",
                         "data dependent", "meeting-by-meeting", "extent and timing", "further", "will continue",
                         "over the coming", "prepared to adjust", "will determine", "outlook for policy"],
    "Balance Sheet": ["balance sheet", "securities holdings", "asset purchase", "quantitative", "treasury securities",
                      "mortgage-backed", "reinvest", "app ", "pepp", "runoff", "liquidity"],
    "Financial Conditions": ["financial conditions", "credit", "bond yields", "lending", "banking system",
                             "financial markets", "spreads"],
}

# phrase -> weight (positive hawkish, negative dovish). Longest match wins.
LEXICON: dict[str, float] = {
    # hawkish
    "remains elevated": 1.5, "remained elevated": 1.5, "somewhat elevated": 0.8, "elevated": 1.0,
    "persistent": 1.0, "persistently": 1.0, "upside risks to inflation": 2.0, "upside risks": 1.2,
    "further tightening": 2.5, "additional policy firming": 2.5, "additional firming": 2.5,
    "raise the target range": 3.0, "increase the target range": 3.0, "raised the target range": 3.0,
    "decided to raise": 3.0, "decided to increase": 3.0, "higher for longer": 2.0,
    "sufficiently restrictive": 1.5, "restrictive for longer": 2.0, "remain restrictive": 1.5,
    "strongly committed": 1.0, "highly attentive to inflation risks": 1.5, "vigilant": 1.2,
    "not yet confident": 1.5, "not appropriate to reduce": 2.0, "inflation pressures": 1.0,
    "price pressures": 0.8, "solid pace": 0.8, "strong": 0.6, "robust": 0.8, "tight": 0.8,
    "accelerat": 0.8, "picked up": 0.8, "moved up": 0.8, "upward pressure": 1.2, "overheat": 1.5,
    "second-round effects": 1.0, "not expect it will be appropriate to reduce": 2.5,
    "not be appropriate to reduce": 2.5, "until it has gained greater confidence": 1.5,
    "maintain the target range": 0.0, "keep the key ecb interest rates unchanged": 0.0, "unemployment rate has remained low": 0.6, "remained low": 0.4,
    # dovish
    "has moderated": -1.2, "moderated": -1.0, "has eased": -1.2, "eased": -1.0, "easing": -0.8,
    "lower the target range": -3.0, "reduce the target range": -3.0, "lowered the target range": -3.0,
    "decided to lower": -3.0, "decided to reduce": -3.0, "cut": -2.0, "rate reductions": -2.0,
    "softened": -1.0, "slowed": -0.8, "slowing": -0.8, "weakened": -1.0, "weaker": -0.8,
    "downside risks": -1.2, "risks to employment": -1.0, "made progress": -1.0, "further progress": -1.0,
    "less restrictive": -1.5, "accommodative": -1.5, "support the economy": -1.0, "cooling": -0.8,
    "subdued": -1.0, "declined": -0.8, "declining": -0.8, "disinflation": -1.0, "rebalancing": -0.6,
    "has risen": 0.0, "moved up but remains low": -0.6, "edged up": -0.2, "gained greater confidence": -1.5,
    "roughly in balance": -0.8, "better balance": -0.8, "uncertainty": -0.3, "headwinds": -0.8,
    "contraction": -1.2, "recession": -1.5,
    # balance sheet
    "reduce its holdings": 1.0, "slow the pace of decline": -1.0, "conclude the reduction": -1.5,
    "asset purchases": -0.8,
}
_LEX_SORTED = sorted(LEXICON.items(), key=lambda kv: len(kv[0]), reverse=True)
CATEGORY_WEIGHT = {"Forward Guidance": 1.6, "Monetary Policy": 1.8, "Inflation": 1.3, "Employment": 1.0,
                   "Growth": 0.8, "Balance Sheet": 0.9, "Financial Conditions": 0.7}


def split_sentences(text: str) -> list[str]:
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"\b(U\.S|e\.g|i\.e|Mr|Ms|Dr|approx|vs)\.", lambda m: m.group(0).replace(".", "§"), t)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“(])", t)
    return [p.replace("§", ".").strip() for p in parts if len(p.strip()) > 3]


def categories(sentence: str) -> list[str]:
    low = sentence.lower()
    out = [c for c, kws in CATEGORIES.items() if any(k in low for k in kws)]
    return out or ["Other"]


def tone(sentence: str) -> tuple[float, list[str]]:
    """Return (tone score, matched phrases). Simple negation flips the next phrase."""
    low = " " + sentence.lower() + " "
    used = [False] * len(low)
    score, hits = 0.0, []
    for phrase, w in _LEX_SORTED:
        for m in re.finditer(r"(?<![a-z])" + re.escape(phrase), low):
            s, e = m.start(), m.end()
            if any(used[s:e]):
                continue
            for i in range(s, e):
                used[i] = True
            window = low[max(0, s - 25):s]
            neg = re.search(r"\b(not|no longer|less|without|unlikely)\b[^.]*$", window) and \
                "not yet confident" not in phrase and "less restrictive" not in phrase
            score += -w if neg else w
            hits.append(("not " if neg else "") + phrase)
    return score, hits


def word_diff(a: str, b: str) -> list[dict]:
    aw, bw = a.split(), b.split()
    sm = difflib.SequenceMatcher(a=aw, b=bw, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            out.append({"op": "equal", "text": " ".join(aw[i1:i2])})
        else:
            if i2 > i1:
                out.append({"op": "delete", "text": " ".join(aw[i1:i2])})
            if j2 > j1:
                out.append({"op": "insert", "text": " ".join(bw[j1:j2])})
    return out


def _direction(delta: float, old_hits: list[str], new_hits: list[str]) -> str:
    if abs(delta) < 0.3:
        added = set(new_hits) - set(old_hits)
        removed = set(old_hits) - set(new_hits)
        if added or removed:
            return "Neutral"
        return "Neutral"
    hawk_added = any(LEXICON.get(h, 0) > 0 for h in set(new_hits) - set(old_hits))
    dove_added = any(LEXICON.get(h, 0) < 0 for h in set(new_hits) - set(old_hits))
    if hawk_added and dove_added and abs(delta) < 1.0:
        return "Mixed"
    return "Hawkish" if delta > 0 else "Dovish"


def _importance(delta: float, cats: list[str], change_type: str) -> str:
    w = max(CATEGORY_WEIGHT.get(c, 0.5) for c in cats)
    m = abs(delta) * w
    if change_type in ("added", "removed") and any(c in ("Monetary Policy", "Forward Guidance") for c in cats):
        m += 1.0
    if m >= 4:
        return "Critical"
    if m >= 2:
        return "High"
    if m >= 0.8:
        return "Medium"
    return "Low"


def _interpret(change: dict) -> str:
    cats = ", ".join(c for c in change["categories"] if c != "Other") or "general language"
    d = change["direction"]
    t = change["type"]
    added = [h for h in change["new_phrases"] if h not in change["old_phrases"]]
    removed = [h for h in change["old_phrases"] if h not in change["new_phrases"]]
    bits = []
    if t == "added":
        bits.append(f"New sentence on {cats}.")
    elif t == "removed":
        bits.append(f"Sentence on {cats} was dropped.")
    else:
        bits.append(f"Wording on {cats} changed.")
    if added:
        bits.append("Added language: " + ", ".join(f"“{a}”" for a in added[:4]) + ".")
    if removed:
        bits.append("Removed language: " + ", ".join(f"“{r}”" for r in removed[:4]) + ".")
    if d == "Hawkish":
        bits.append("The change signals less willingness to ease / more concern about inflation (hawkish).")
    elif d == "Dovish":
        bits.append("The change signals more room to ease or less concern about inflation (dovish).")
    elif d == "Mixed":
        bits.append("The change contains both hawkish and dovish elements.")
    else:
        bits.append("The change does not materially alter the policy signal.")
    return " ".join(bits)


@dataclass
class Comparison:
    changes: list[dict] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    old_tone: float = 0.0
    new_tone: float = 0.0
    tone_shift: float = 0.0
    direction: str = "Neutral"
    summary: dict = field(default_factory=dict)


def statement_tone(text: str) -> float:
    """Whole-statement tone on -100..+100."""
    sents = split_sentences(text)
    if not sents:
        return 0.0
    total = 0.0
    for s in sents:
        sc, _ = tone(s)
        w = max(CATEGORY_WEIGHT.get(c, 0.5) for c in categories(s))
        total += sc * w
    import math

    return round(100 * math.tanh(total / 12.0), 1)


def overall_direction(shift: float, hawk: int, dove: int) -> str:
    """Direction of a whole statement change from its tone shift and the hawkish/dovish edits."""
    if abs(shift) >= 5:
        if hawk and dove and abs(shift) < 15:
            return "Mixed"
        return "Hawkish" if shift > 0 else "Dovish"
    return "Mixed" if hawk and dove else "Neutral"


def compare(previous: str, latest: str) -> Comparison:
    a, b = split_sentences(previous), split_sentences(latest)
    sm = difflib.SequenceMatcher(a=[s.lower() for s in a], b=[s.lower() for s in b], autojunk=False)
    changes: list[dict] = []
    unchanged: list[str] = []

    def add(old: str | None, new: str | None, typ: str) -> None:
        o_score, o_hits = tone(old) if old else (0.0, [])
        n_score, n_hits = tone(new) if new else (0.0, [])
        delta = n_score - o_score
        cats = sorted(set(categories(old or "") + categories(new or "")) - ({"Other"} if (old or new) else set())) \
            or ["Other"]
        ch = {
            "type": typ, "previous": old, "latest": new,
            "diff": word_diff(old or "", new or "") if typ == "modified" else None,
            "categories": cats, "old_phrases": o_hits, "new_phrases": n_hits,
            "tone_delta": round(delta, 2), "direction": _direction(delta, o_hits, n_hits),
        }
        ch["importance"] = _importance(delta, cats, typ)
        ch["what_changed"] = _what_changed(ch)
        ch["interpretation"] = _interpret(ch)
        ch["color"] = {"Hawkish": "red", "Dovish": "green", "Mixed": "yellow"}.get(ch["direction"], "yellow"
                                                                                   if ch["importance"] in
                                                                                   ("High", "Critical") else "grey")
        changes.append(ch)

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            unchanged.extend(b[j1:j2])
            continue
        olds, news = a[i1:i2], b[j1:j2]
        # pair similar sentences as modifications
        used_new: set[int] = set()
        for o in olds:
            best, best_r = None, 0.0
            for k, n in enumerate(news):
                if k in used_new:
                    continue
                r = difflib.SequenceMatcher(a=o.lower().split(), b=n.lower().split(), autojunk=False).ratio()
                if r > best_r:
                    best, best_r = k, r
            if best is not None and best_r >= 0.5:
                used_new.add(best)
                add(o, news[best], "modified")
            else:
                add(o, None, "removed")
        for k, n in enumerate(news):
            if k not in used_new:
                add(None, n, "added")
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    changes.sort(key=lambda c: order[c["importance"]])
    old_t, new_t = statement_tone(previous), statement_tone(latest)
    shift = round(new_t - old_t, 1)
    hawk = sum(1 for c in changes if c["direction"] == "Hawkish")
    dove = sum(1 for c in changes if c["direction"] == "Dovish")
    direction = overall_direction(shift, hawk, dove)
    summary = {"sentences_previous": len(a), "sentences_latest": len(b), "changed": len(changes),
               "unchanged": len(unchanged), "hawkish_changes": hawk, "dovish_changes": dove,
               "critical": sum(1 for c in changes if c["importance"] == "Critical"),
               "high": sum(1 for c in changes if c["importance"] == "High"),
               "tone_previous": old_t, "tone_latest": new_t, "tone_shift": shift, "direction": direction}
    return Comparison(changes, unchanged, old_t, new_t, shift, direction, summary)


def _what_changed(ch: dict) -> str:
    if ch["type"] == "added":
        return "New sentence added"
    if ch["type"] == "removed":
        return "Sentence removed"
    ins = [d["text"] for d in ch["diff"] or [] if d["op"] == "insert"]
    dels = [d["text"] for d in ch["diff"] or [] if d["op"] == "delete"]
    parts = []
    if dels:
        parts.append("removed “" + "”, “".join(dels[:3]) + "”")
    if ins:
        parts.append("added “" + "”, “".join(ins[:3]) + "”")
    return "; ".join(parts).capitalize() if parts else "Minor wording change"
