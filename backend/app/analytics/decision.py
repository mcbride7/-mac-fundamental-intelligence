"""Read the rate decision (and new rate, when stated) out of a central bank's decision statement. Pure."""
from __future__ import annotations

import re

_FRAC = {"1/4": 0.25, "1/2": 0.5, "3/4": 0.75, "1/8": 0.125, "3/8": 0.375, "5/8": 0.625, "7/8": 0.875}

HOLD = [r"(decided|voted|agreed|decision)\b[^.]{0,60}?\bto\s+(maintain|keep|leave|hold)\b",
        r"\b(maintain|maintained|keeps?|kept|leaves?|left|holds?|held)\s+(?:the\s+)?(?:\w+\s+){0,6}?(?:rates?|target range|bank rate|cash rate)\b[^.]{0,60}\bunchanged",
        r"\b(?:rates?|bank rate|cash rate|target range)\b[^.]{0,40}\b(unchanged|on hold|maintained)\b",
        r"\bbank rate maintained\b"]
CUT = [r"(decided|voted|agreed|decision)\b[^.]{0,60}?\bto\s+(lower|reduce|cut)\b",
       r"\b(lowered|reduced|cut)s?\s+(?:the\s+)?(?:\w+\s+){0,6}?(?:rates?|target range|bank rate|cash rate)\b",
       r"\bbank rate reduced\b"]
HIKE = [r"(decided|voted|agreed|decision)\b[^.]{0,60}?\bto\s+(raise|increase|lift)\b",
        r"\b(raised|increased|lifted)\s+(?:the\s+)?(?:\w+\s+){0,6}?(?:rates?|target range|bank rate|cash rate)\b",
        r"\bbank rate increased\b"]


def _num(text: str) -> float | None:
    """'3-3/4' -> 3.75, '4' -> 4.0, '2.25' -> 2.25."""
    t = text.strip()
    m = re.fullmatch(r"(\d+)(?:[-\s](\d/\d))?", t)
    if m:
        return int(m.group(1)) + (_FRAC.get(m.group(2), 0) if m.group(2) else 0)
    m = re.fullmatch(r"(\d/\d)", t)
    if m:
        return _FRAC.get(m.group(1))
    try:
        return float(t)
    except ValueError:
        return None


def parse_decision(text: str, cb_code: str | None = None) -> tuple[str | None, float | None]:
    """-> (HOLD | CUT | HIKE | None, new policy rate or None). The earliest decision wording in the text wins
    (decision statements open with the decision)."""
    low = re.sub(r"\s+", " ", text or "").lower()
    best = None
    for label, pats in (("HOLD", HOLD), ("CUT", CUT), ("HIKE", HIKE)):
        for p in pats:
            m = re.search(p, low)
            if m and (best is None or m.start() < best[1]):
                best = (label, m.start())
    decision = best[0] if best else None
    rate = None
    m = re.search(r"target range for the federal funds rate (?:by [^.]{0,40}? points? )?(?:at|to) ([\d\-\s/]+?) to ([\d\-\s/]+?) percent", low)
    if m:
        rate = _num(m.group(2))  # the app stores the Fed's upper bound
    if rate is None:
        for p in (r"deposit facility[^.]{0,120}?(\d+(?:\.\d+)?)\s*%",
                  r"bank rate[^.]{0,80}?(\d+(?:\.\d+)?)\s*%",
                  r"(?:cash rate|official cash rate|policy rate|repo rate|target for the overnight rate|policy interest rate)"
                  r"[^.]{0,100}?(-?\d+(?:\.\d+)?)\s*(?:%|per ?cent)"):
            m = re.search(p, low)
            if m:
                rate = float(m.group(1))
                break
    return decision, rate
