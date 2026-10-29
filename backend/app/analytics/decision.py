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


_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}


def parse_dissent(text: str) -> dict:
    """Votes against the decision and which way they leaned.
    -> {"hawkish": n, "dovish": n, "split": "7-2" or None}. Covers the Fed ('Voting against the action was X, who
    preferred to lower...'), the BoE ('7-2 ... two members preferring to reduce Bank Rate') and similar wording."""
    low = re.sub(r"\s+", " ", text or "").lower()
    out = {"hawkish": 0, "dovish": 0, "split": None}
    m = re.search(r"\b(\d)\s*[-–]\s*(\d)\b(?=[^.]{0,80}\b(?:vote|voted|majority|members?))|majority of (\d)\s*[-–]\s*(\d)", low)
    if m:
        a, b = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        out["split"] = f"{a}-{b}"
    for m in re.finditer(r"(?:(\d|one|two|three|four|five)\s+members?\s+)?(?:who\s+)?(?:voted|preferring|preferred|favou?red)\s+"
                         r"(?:instead\s+)?to\s+(lower|reduce|cut|raise|increase)", low):
        n = m.group(1)
        k = int(n) if n and n.isdigit() else _WORDNUM.get(n or "", 1)
        out["dovish" if m.group(2) in ("lower", "reduce", "cut") else "hawkish"] += k
    return out


def _clip(x: float, lim: float) -> float:
    return max(-lim, min(lim, x))


def characterise(decision: str | None, tone_now: float | None, tone_prev: float | None, dissent: dict | None,
                 expected: str | None = None, prob_cut: float | None = None, prob_hike: float | None = None,
                 inflation: float | None = None, target: float | None = None) -> dict | None:
    """Hawkish hold / dovish hold (or hawkish cut, dovish hike...) from:
      - statement wording: change in tone vs the previous statement (35%) and the tone itself (15%)
      - votes against the decision and their direction (25%)
      - surprise vs what was expected / priced before the meeting (15%)
      - inflation vs target backdrop (10%)
    Each part runs -1 (dovish) .. +1 (hawkish); the weighted average decides the label (±0.25)."""
    if decision not in ("HOLD", "CUT", "HIKE"):
        return None
    parts: dict[str, tuple[float, float]] = {}
    reasons: list[str] = []
    if tone_now is not None and tone_prev is not None:
        sh = tone_now - tone_prev
        parts["tone_shift"] = (_clip(sh / 20, 1), 0.35)
        if abs(sh) >= 5:
            reasons.append(f"Statement wording turned more {'hawkish' if sh > 0 else 'dovish'} ({tone_prev:+.0f} → {tone_now:+.0f})")
        else:
            reasons.append(f"Statement wording about the same as last time ({tone_prev:+.0f} → {tone_now:+.0f})")
    if tone_now is not None:
        parts["tone_level"] = (_clip(tone_now / 40, 1), 0.15)
        if abs(tone_now) >= 15:
            reasons.append(f"Overall wording leans {'hawkish' if tone_now > 0 else 'dovish'} ({tone_now:+.0f})")
    if dissent is not None:
        net = dissent.get("hawkish", 0) - dissent.get("dovish", 0)
        if dissent.get("hawkish") or dissent.get("dovish"):
            parts["votes"] = (_clip(net / 2, 1), 0.25)
            bits = []
            if dissent.get("hawkish"):
                bits.append(f"{dissent['hawkish']} voted for higher rates")
            if dissent.get("dovish"):
                bits.append(f"{dissent['dovish']} voted for lower rates")
            reasons.append("Vote split" + (f" {dissent['split']}" if dissent.get("split") else "") + ": " + ", ".join(bits))
        else:
            parts["votes"] = (0.0, 0.25)
            reasons.append("No votes against the decision")
    exp = (expected or "").upper() or None
    if exp is None and prob_cut is not None and prob_hike is not None:
        exp = "CUT" if prob_cut >= 50 else "HIKE" if prob_hike >= 50 else "HOLD"
    if exp:
        order = {"CUT": -1, "HOLD": 0, "HIKE": 1}
        surprise = order[decision] - order.get(exp, 0)
        parts["surprise"] = (_clip(float(surprise), 1), 0.15)
        reasons.append(f"Market expected {exp.lower()}: "
                       + ("in line" if surprise == 0 else f"{'hawkish' if surprise > 0 else 'dovish'} surprise"))
    if inflation is not None and target is not None:
        gap = inflation - target
        parts["backdrop"] = (_clip(gap / 1.0, 1), 0.10)
        if abs(gap) >= 0.3:
            reasons.append(f"Inflation {inflation:.1f}% is {'above' if gap > 0 else 'below'} the {target:g}% target")
    if not parts:
        return {"label": decision.title() if decision != "HOLD" else "Hold", "score": None, "reasons": [],
                "lean": "neutral"}
    w = sum(wt for _, wt in parts.values())
    sc = round(sum(v * wt for v, wt in parts.values()) / w, 2)
    lean = "hawkish" if sc >= 0.25 else "dovish" if sc <= -0.25 else "neutral"
    base = {"HOLD": "hold", "CUT": "cut", "HIKE": "hike"}[decision]
    label = f"{'Hawkish' if lean == 'hawkish' else 'Dovish' if lean == 'dovish' else 'Neutral'} {base}"
    if decision == "HIKE" and lean != "dovish":
        label = "Hawkish hike" if lean == "hawkish" else "Hike"
    if decision == "CUT" and lean != "hawkish":
        label = "Dovish cut" if lean == "dovish" else "Cut"
    return {"label": label, "score": sc, "lean": lean, "reasons": reasons,
            "coverage": round(w / 1.0, 2)}
