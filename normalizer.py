"""Normalisation (Section 66.3): map free-text indicator names to internal indicator
codes, and convert units. Pure functions operating on plain dicts so they are
testable without a database."""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.extraction.text_parser import COUNTRY_TOKENS

_STOP = {"the", "rate", "index", "s.a", "sa", "nsa", "flash", "prelim", "final", "annualized",
         "annualised", "q", "change", "%"}


@dataclass
class IndicatorRef:
    code: str
    name: str
    country: str
    currency: str
    unit: str
    transform: str | None
    aliases: list[str]


def _clean(text: str, country: str | None = None) -> str:
    t = text.lower()
    t = re.sub(r"\b(y/y|yoy|m/m|mom|q/q|qoq)\b", " ", t)
    t = re.sub(r"[()\[\],:;]", " ", t)
    if country:
        for tok in sorted(COUNTRY_TOKENS.get(country, []), key=len, reverse=True):
            t = re.sub(rf"(?<![a-z]){re.escape(tok)}(?![a-z])", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9/]+", text.lower()) if w not in _STOP}


def map_indicator(
    text: str,
    country: str | None,
    transform: str | None,
    indicators: list[IndicatorRef],
) -> tuple[str | None, float, list[tuple[str, float]]]:
    """Return (best code, confidence 0-100, ranked candidates)."""
    if not text:
        return None, 0.0, []
    name = _clean(text, country)
    name_tokens = _tokens(name)
    is_core = "core" in name_tokens
    scored: list[tuple[str, float]] = []
    for ind in indicators:
        if country and ind.country != country:
            continue
        best = 0.0
        candidates = [ind.name, ind.code.replace("_", " ")] + list(ind.aliases)
        for alias in candidates:
            a = _clean(alias, ind.country)
            if not a:
                continue
            a_tokens = _tokens(a)
            if ("core" in a_tokens) != is_core:
                continue
            if a == name:
                s = 95.0
            elif re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", name) or \
                    re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", a):
                s = 70.0 + 20.0 * min(len(a), len(name)) / max(len(a), len(name))
            else:
                inter = len(a_tokens & name_tokens)
                union = len(a_tokens | name_tokens) or 1
                s = 75.0 * inter / union
            best = max(best, s)
        if best == 0:
            continue
        if transform and ind.transform:
            if transform == ind.transform or (transform == "qoq" and ind.transform == "qoq_saar"):
                best += 5
            elif ind.transform in ("yoy", "mom", "qoq", "qoq_saar"):
                best -= 15
        elif not transform and ind.transform == "mom" and "m/m" not in text.lower():
            best -= 5  # default to the y/y headline when unspecified
        if not country:
            best -= 15
        scored.append((ind.code, round(min(best, 99.0), 1)))
    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored or scored[0][1] < 35:
        return None, scored[0][1] if scored else 0.0, scored[:5]
    top = scored[0]
    # ambiguity penalty
    if len(scored) > 1 and scored[1][1] >= top[1] - 3:
        return top[0], round(top[1] - 15, 1), scored[:5]
    return top[0], top[1], scored[:5]


UNIT_FACTORS = {("m", "k"): 1000.0, ("bn", "m"): 1000.0, ("bn", "k"): 1_000_000.0, ("k", "m"): 0.001}


def convert_unit(value: float, from_unit: str | None, to_unit: str) -> tuple[float, str | None]:
    """Convert value to the indicator's unit. Returns (value, note)."""
    if from_unit is None or from_unit == to_unit:
        if to_unit == "k" and from_unit is None and abs(value) >= 10_000:
            return value / 1000.0, f"Converted {value:,.0f} to {value / 1000:,.1f}k"
        return value, None
    f = UNIT_FACTORS.get((from_unit, to_unit))
    if f:
        return value * f, f"Converted {value}{from_unit} to {value * f}{to_unit}"
    if from_unit == "%" and to_unit == "index":
        return value, None
    return value, f"Unit '{from_unit}' differs from indicator unit '{to_unit}'"
