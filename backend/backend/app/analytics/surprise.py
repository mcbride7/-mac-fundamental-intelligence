"""Economic surprise engine (Section 28). Pure functions."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass
class SurpriseResult:
    market_surprise: float | None
    cb_surprise: float | None
    historical_z: float | None
    classification: str
    policy_direction: str  # Hawkish | Dovish | Neutral
    basis: str  # what the classification was based on


def market_surprise(actual: float | None, consensus: float | None) -> float | None:
    if actual is None or consensus is None:
        return None
    return round(actual - consensus, 4)


def cb_surprise(actual: float | None, projection: float | None) -> float | None:
    if actual is None or projection is None:
        return None
    return round(actual - projection, 4)


def historical_z(surprise: float | None, past: list[float], min_n: int = 5) -> float | None:
    if surprise is None:
        return None
    vals = [p for p in past if p is not None]
    if len(vals) < min_n:
        return None
    sd = statistics.pstdev(vals)
    if sd == 0:
        return None
    mu = statistics.fmean(vals)
    return round((surprise - mu) / sd, 2)


def classify_z(z: float) -> str:
    a = abs(z)
    side = "Upside" if z > 0 else "Downside"
    if a >= 2:
        return f"Major {side} Surprise"
    if a >= 1:
        return f"{side} Surprise"
    if a >= 0.5:
        return f"Slight {side} Surprise"
    return "In Line"


def policy_direction(surprise: float | None, higher_is: str, threshold: float = 0.0) -> str:
    if surprise is None or abs(surprise) <= threshold:
        return "Neutral"
    if higher_is == "neutral":
        return "Neutral"
    hawkish = surprise > 0 if higher_is == "hawkish" else surprise < 0
    return "Hawkish" if hawkish else "Dovish"


def default_scale(unit: str, transform: str | None, history_changes: list[float]) -> float:
    """Typical size of a surprise when no surprise history exists."""
    vals = [abs(c) for c in history_changes if c is not None]
    if len(vals) >= 6:
        return max(statistics.fmean(vals), 1e-6)
    if unit == "k":
        return 60.0
    if unit == "index":
        return 1.5
    if transform in ("mom", "qoq"):
        return 0.15
    if transform == "qoq_saar":
        return 0.6
    return 0.15


def evaluate(actual: float, consensus: float | None, projection: float | None, past_surprises: list[float],
             history_changes: list[float], unit: str, transform: str | None, higher_is: str) -> SurpriseResult:
    ms = market_surprise(actual, consensus)
    cs = cb_surprise(actual, projection)
    z = historical_z(ms, past_surprises)
    basis = "historical surprise distribution"
    if z is None and ms is not None:
        scale = default_scale(unit, transform, history_changes)
        z = round(ms / scale, 2) if scale else None
        basis = "typical monthly change (insufficient surprise history)"
    if z is None:
        if cs is not None:
            scale = default_scale(unit, transform, history_changes) * 2
            zc = cs / scale if scale else 0.0
            cls = classify_z(zc).replace("Surprise", "vs Projection")
            return SurpriseResult(ms, cs, None, cls, policy_direction(cs, higher_is), "central-bank projection")
        return SurpriseResult(ms, cs, None, "No Forecast Available", "Neutral", "no consensus or projection")
    if math.isnan(z):  # pragma: no cover
        z = 0.0
    cls = classify_z(z)
    direction = policy_direction(ms, higher_is) if cls != "In Line" else "Neutral"
    return SurpriseResult(ms, cs, z, cls, direction, basis)
