"""Forecast intelligence (Sections 18-27, 48-49). Pure functions."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

# "In line" thresholds and accuracy scales, per projection variable (percentage points)
THRESHOLDS = {"inflation": 0.2, "core_inflation": 0.2, "gdp": 0.3, "unemployment": 0.2, "policy_rate": 0.25}
ACCURACY_SCALE = {"inflation": 0.75, "core_inflation": 0.6, "gdp": 1.0, "unemployment": 0.5, "policy_rate": 0.75}

# For "where are we now" — direction of the policy implication when actual > projection
HIGHER_IS = {"inflation": "Hawkish", "core_inflation": "Hawkish", "gdp": "Hawkish", "unemployment": "Dovish",
             "policy_rate": "Hawkish"}


def classify_vs_projection(diff: float, variable: str) -> str:
    t = THRESHOLDS.get(variable, 0.2)
    if diff >= 2 * t:
        return "Significantly Above Projection"
    if diff >= t:
        return "Above Projection"
    if diff <= -2 * t:
        return "Significantly Below Projection"
    if diff <= -t:
        return "Below Projection"
    return "In Line"


@dataclass
class ThreeWay:
    actual: float
    cb: float | None
    market: float | None
    economist: float | None
    cb_error: float | None
    market_error: float | None
    economist_error: float | None
    more_accurate: str | None
    cb_classification: str | None


def three_way(actual: float, cb: float | None, market: float | None, economist: float | None = None,
              variable: str | None = None) -> ThreeWay:
    err = lambda f: None if f is None else round(actual - f, 4)  # noqa: E731
    ce, me, ee = err(cb), err(market), err(economist)
    cands = {k: abs(v) for k, v in (("central_bank", ce), ("market", me), ("economist", ee)) if v is not None}
    best = None
    if cands:
        m = min(cands.values())
        winners = [k for k, v in cands.items() if abs(v - m) < 1e-9]
        best = winners[0] if len(winners) == 1 else "tie"
    cls = classify_vs_projection(ce, variable or "inflation") if ce is not None else None
    return ThreeWay(actual, cb, market, economist, ce, me, ee, best, cls)


@dataclass
class Accuracy:
    n: int
    mae: float
    rmse: float
    mean_error: float
    score: float


def accuracy(errors: list[float], variable: str) -> Accuracy | None:
    e = [x for x in errors if x is not None]
    if not e:
        return None
    mae = statistics.fmean(abs(x) for x in e)
    rmse = math.sqrt(statistics.fmean(x * x for x in e))
    scale = ACCURACY_SCALE.get(variable, 0.75)
    score = 100.0 * math.exp(-mae / scale)
    return Accuracy(len(e), round(mae, 4), round(rmse, 4), round(statistics.fmean(e), 4), round(score, 1))


WINDOWS = {"last4": 4, "last8": 8, "last12": 12}


def windowed(errors_by_date: list[tuple[str, float]], window: str, as_of_year: int) -> list[float]:
    """errors_by_date: [(YYYY-MM or YYYY, error)] oldest->newest."""
    if window in WINDOWS:
        return [e for _, e in errors_by_date[-WINDOWS[window]:]]
    years = {"2y": 2, "5y": 5}[window]
    return [e for d, e in errors_by_date if int(d[:4]) > as_of_year - years]


@dataclass
class BiasResult:
    classification: str
    mean_error: float
    same_sign_share: float
    n: int
    t_stat: float | None
    explanation: str


def bias(errors: list[float], variable: str) -> BiasResult:
    e = [x for x in errors if x is not None]
    n = len(e)
    if n < 3:
        return BiasResult("Neutral", statistics.fmean(e) if e else 0.0, 0.0, n, None,
                          "Not enough history to detect a systematic bias.")
    mean = statistics.fmean(e)
    sd = statistics.stdev(e) if n > 1 else 0.0
    t = mean / (sd / math.sqrt(n)) if sd > 0 else (math.copysign(99.0, mean) if mean else 0.0)
    pos = sum(1 for x in e if x > 0) / n
    neg = sum(1 for x in e if x < 0) / n
    share = max(pos, neg)
    systematic = abs(t) >= 2.0 or (share >= 0.75 and n >= 4 and abs(mean) >= THRESHOLDS.get(variable, 0.2) / 2)
    if not systematic:
        return BiasResult("Neutral", round(mean, 4), round(share, 2), n, round(t, 2),
                          f"Errors are not systematically one-sided ({share:.0%} same sign, t={t:.1f}).")
    under = mean > 0  # actual above forecast
    label = {
        "inflation": "Inflation underestimation" if under else "Inflation overestimation",
        "core_inflation": "Inflation underestimation" if under else "Inflation overestimation",
        "gdp": "Growth underestimation" if under else "Growth overestimation",
        # unemployment higher than forecast = forecaster was too optimistic about the labour market
        "unemployment": "Optimistic" if under else "Pessimistic",
        "policy_rate": "Pessimistic" if under else "Optimistic",
    }.get(variable, "Neutral")
    verb = "underestimated" if under else "overestimated"
    return BiasResult(label, round(mean, 4), round(share, 2), n, round(t, 2),
                      f"{variable.replace('_', ' ').title()} was {verb} in {share:.0%} of {n} forecasts "
                      f"(mean error {mean:+.2f} pp, t={t:.1f}).")


@dataclass
class Revision:
    momentum: str
    total_change: float
    interpretation: str
    path: list = field(default_factory=list)


def revision_momentum(values: list[float], variable: str) -> Revision:
    if len(values) < 2:
        return Revision("FLAT", 0.0, "Only one projection vintage available.", values)
    steps = [b - a for a, b in zip(values[:-1], values[1:])]
    total = values[-1] - values[0]
    ups = sum(1 for s in steps if s > 0.05)
    downs = sum(1 for s in steps if s < -0.05)
    if ups and downs and abs(total) < 0.1:
        m = "MIXED"
    elif total > 0.05 and downs <= ups:
        m = "POSITIVE"
    elif total < -0.05 and ups <= downs:
        m = "NEGATIVE"
    elif abs(total) <= 0.05:
        m = "FLAT"
    else:
        m = "MIXED"
    name = {"gdp": "Growth", "inflation": "Inflation", "core_inflation": "Core inflation",
            "unemployment": "Unemployment", "policy_rate": "Policy-rate"}.get(variable, variable)
    if m == "POSITIVE":
        text = f"{name} expectations are rising ({values[0]:.1f} → {values[-1]:.1f})."
        if variable == "gdp":
            text = f"Growth expectations are improving ({values[0]:.1f}% → {values[-1]:.1f}%)."
        if variable == "unemployment":
            text = f"The labour-market outlook is deteriorating: unemployment projections rose " \
                   f"({values[0]:.1f}% → {values[-1]:.1f}%)."
    elif m == "NEGATIVE":
        text = f"{name} expectations are falling ({values[0]:.1f} → {values[-1]:.1f})."
        if variable == "gdp":
            text = f"Growth expectations are deteriorating ({values[0]:.1f}% → {values[-1]:.1f}%)."
        if variable == "unemployment":
            text = f"The labour-market outlook is improving ({values[0]:.1f}% → {values[-1]:.1f}%)."
    elif m == "MIXED":
        text = f"{name} projections have been revised in both directions."
    else:
        text = f"{name} projections are broadly unchanged."
    return Revision(m, round(total, 3), text, values)


def policy_implication(deviations: dict[str, float]) -> dict:
    """Section 27: translate deviations from projection into a policy implication.
    deviations: variable -> actual minus projection."""
    parts, score, explained = [], 0.0, []
    weights = {"inflation": 1.0, "core_inflation": 1.2, "gdp": 0.6, "unemployment": 0.8}
    for var, d in deviations.items():
        if d is None or var not in weights:
            continue
        cls = classify_vs_projection(d, var)
        if cls == "In Line":
            parts.append({"variable": var, "deviation": d, "classification": cls, "implication": "Neutral"})
            continue
        direction = HIGHER_IS[var] if d > 0 else ("Dovish" if HIGHER_IS[var] == "Hawkish" else "Hawkish")
        mag = min(2.0, abs(d) / THRESHOLDS.get(var, 0.2)) / 2.0
        score += (1 if direction == "Hawkish" else -1) * weights[var] * mag
        parts.append({"variable": var, "deviation": round(d, 3), "classification": cls, "implication": direction})
    hawk = [p for p in parts if p["implication"] == "Hawkish"]
    dove = [p for p in parts if p["implication"] == "Dovish"]
    if hawk and dove:
        overall = "Mixed / Moderately Hawkish" if score > 0.3 else ("Mixed / Moderately Dovish" if score < -0.3
                                                                     else "Mixed")
        h = ", ".join(p["variable"].replace("_", " ") for p in hawk)
        d = ", ".join(p["variable"].replace("_", " ") for p in dove)
        explained.append(f"{h.capitalize()} argue{'s' if len(hawk) == 1 else ''} for restrictive policy, while "
                         f"{d} argue{'s' if len(dove) == 1 else ''} for caution. The policy outlook is therefore "
                         "mixed rather than one-directional.")
    elif hawk:
        overall = "Hawkish" if score >= 1 else "Moderately Hawkish"
        explained.append("Data are running on the hawkish side of the central bank's projections.")
    elif dove:
        overall = "Dovish" if score <= -1 else "Moderately Dovish"
        explained.append("Data are running on the dovish side of the central bank's projections.")
    else:
        overall = "Neutral"
        explained.append("Data are broadly in line with the central bank's projections.")
    return {"overall": overall, "score": round(score, 3), "components": parts, "explanation": explained}


def forecastability(errors: list[float], changes: list[float]) -> float | None:
    """0-100: how small forecast errors are relative to how much the series moves."""
    e = [abs(x) for x in errors if x is not None]
    c = [abs(x) for x in changes if x is not None]
    if len(e) < 4 or len(c) < 4:
        return None
    typical_move = statistics.fmean(c) or 1e-9
    ratio = statistics.fmean(e) / typical_move
    return round(100.0 * math.exp(-ratio), 1)
