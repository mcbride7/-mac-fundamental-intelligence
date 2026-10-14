"""Central-bank policy score, shift, surprise and divergence (Sections 6, 10, 11, 13). Pure."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

WEIGHTS = {
    "inflation": 0.20,          # inflation vs target
    "inflation_vs_projection": 0.10,
    "employment": 0.10,
    "growth": 0.08,
    "rate_decision": 0.12,
    "statement_language": 0.15,  # includes forward guidance
    "rate_expectations": 0.12,
    "financial_conditions": 0.05,
    "surprises": 0.08,
}


@dataclass
class PolicyInputs:
    inflation: float | None = None              # latest headline/core y/y
    inflation_target: float | None = None
    inflation_vs_projection: float | None = None  # actual - projection (pp)
    unemployment_change_6m: float | None = None  # pp change; rising = dovish
    unemployment_vs_projection: float | None = None
    growth_vs_projection: float | None = None   # pp
    pmi: float | None = None
    last_decision: str | None = None             # HIKE | CUT | HOLD
    last_change_bps: float | None = None
    statement_tone: float | None = None          # -100..100
    implied_12m_change_bps: float | None = None  # market-implied path
    prob_cut: float | None = None
    prob_hike: float | None = None
    yield_2y_change_1m_bps: float | None = None  # financial conditions proxy
    surprise_index: float | None = None          # avg policy-signed surprise z
    policy_rate: float | None = None
    evidence_quality: float = 100.0


@dataclass
class PolicyScoreResult:
    score: float
    classification: str
    direction: str
    confidence: float
    components: dict = field(default_factory=dict)
    explanation: list = field(default_factory=list)


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


def classify(score: float) -> str:
    if score >= 85:
        return "Extremely Hawkish"
    if score >= 70:
        return "Hawkish"
    if score >= 57:
        return "Moderately Hawkish"
    if score > 43:
        return "Neutral"
    if score > 30:
        return "Moderately Dovish"
    if score > 15:
        return "Dovish"
    return "Extremely Dovish"


def policy_direction(policy_rate: float | None, inflation: float | None, neutral_real: float = 0.5) -> str:
    if policy_rate is None or inflation is None:
        return "UNKNOWN"
    real = policy_rate - inflation
    if real >= neutral_real + 0.75:
        return "RESTRICTIVE"
    if real <= neutral_real - 1.0:
        return "ACCOMMODATIVE"
    return "NEUTRAL"


def score(inp: PolicyInputs) -> PolicyScoreResult:
    comp: dict[str, float] = {}
    why: list[str] = []
    if inp.inflation is not None and inp.inflation_target is not None:
        gap = inp.inflation - inp.inflation_target
        comp["inflation"] = _clip(math.tanh(gap / 1.5))
        why.append(f"Inflation {inp.inflation:.1f}% vs {inp.inflation_target:.1f}% target "
                   f"({'above' if gap > 0 else 'below'} by {abs(gap):.1f} pp)")
    if inp.inflation_vs_projection is not None:
        comp["inflation_vs_projection"] = _clip(inp.inflation_vs_projection / 0.6)
        why.append(f"Inflation {inp.inflation_vs_projection:+.1f} pp vs the bank's projection")
    emp = []
    if inp.unemployment_change_6m is not None:
        emp.append(_clip(-inp.unemployment_change_6m / 0.5))
    if inp.unemployment_vs_projection is not None:
        emp.append(_clip(-inp.unemployment_vs_projection / 0.5))
    if emp:
        comp["employment"] = sum(emp) / len(emp)
        why.append("Labour market " + ("tighter" if comp["employment"] > 0 else "looser") + " than expected/trend")
    gr = []
    if inp.growth_vs_projection is not None:
        gr.append(_clip(inp.growth_vs_projection / 0.8))
    if inp.pmi is not None:
        gr.append(_clip((inp.pmi - 50) / 5))
    if gr:
        comp["growth"] = sum(gr) / len(gr)
    if inp.last_decision:
        d = inp.last_decision.upper()
        bps = abs(inp.last_change_bps or 25)
        comp["rate_decision"] = {"HIKE": min(1.0, bps / 50), "CUT": -min(1.0, bps / 50), "HOLD": 0.0}.get(d, 0.0)
        why.append(f"Last decision: {d.lower()}" + (f" {bps:.0f} bps" if d != "HOLD" else ""))
    if inp.statement_tone is not None:
        comp["statement_language"] = _clip(inp.statement_tone / 60)
        why.append(f"Statement tone {inp.statement_tone:+.0f}/100")
    re_parts = []
    if inp.implied_12m_change_bps is not None:
        re_parts.append(_clip(inp.implied_12m_change_bps / 100))
    if inp.prob_cut is not None and inp.prob_hike is not None:
        re_parts.append(_clip((inp.prob_hike - inp.prob_cut) / 60))
    if re_parts:
        comp["rate_expectations"] = sum(re_parts) / len(re_parts)
        why.append("Markets price " + ("tightening" if comp["rate_expectations"] > 0.1 else
                                       "easing" if comp["rate_expectations"] < -0.1 else "little change"))
    if inp.yield_2y_change_1m_bps is not None:
        comp["financial_conditions"] = _clip(inp.yield_2y_change_1m_bps / 40)
    if inp.surprise_index is not None:
        comp["surprises"] = _clip(inp.surprise_index / 1.5)
        why.append(f"Recent data surprises {'hawkish' if inp.surprise_index > 0 else 'dovish'} "
                   f"({inp.surprise_index:+.2f})")
    if not comp:
        return PolicyScoreResult(50.0, "Neutral", "UNKNOWN", 0.0, {}, ["No inputs available"])
    wsum = sum(WEIGHTS[k] for k in comp)
    raw = sum(WEIGHTS[k] * v for k, v in comp.items()) / wsum
    coverage = wsum / sum(WEIGHTS.values())
    # With few inputs, shrink towards neutral so one data point cannot make a bank "extremely" anything.
    shrink = min(1.0, coverage / 0.6)
    s = round(50 + 50 * raw * shrink, 1)
    if shrink < 1:
        why.append(f"Score shrunk towards neutral: only {coverage:.0%} of inputs available")
    signs = [1 if v > 0.1 else -1 if v < -0.1 else 0 for v in comp.values()]
    nz = [x for x in signs if x]
    agreement = (abs(sum(nz)) / len(nz)) if nz else 0.5
    conf = round(100 * (0.35 + 0.4 * coverage + 0.25 * agreement) * (inp.evidence_quality / 100), 1)
    return PolicyScoreResult(s, classify(s), policy_direction(inp.policy_rate, inp.inflation), min(conf, 99.0),
                             {k: round(v, 3) for k, v in comp.items()}, why)


def shift(previous: float | None, current: float) -> tuple[float | None, str]:
    if previous is None:
        return None, "First reading"
    d = round(current - previous, 1)
    if d >= 15:
        return d, "Significant Hawkish Shift"
    if d >= 5:
        return d, "Moderately Hawkish Shift"
    if d <= -15:
        return d, "Significant Dovish Shift"
    if d <= -5:
        return d, "Moderately Dovish Shift"
    return d, "No Material Shift"


def explain_shift(prev_components: dict, cur_components: dict) -> list[str]:
    out = []
    for k in sorted(set(prev_components) | set(cur_components)):
        a, b = prev_components.get(k), cur_components.get(k)
        if a is None or b is None:
            continue
        if abs(b - a) >= 0.15:
            out.append(f"{k.replace('_', ' ').capitalize()} moved {'hawkish' if b > a else 'dovish'} "
                       f"({a:+.2f} → {b:+.2f})")
    return out


def tone_label(t: float) -> str:
    s = 50 + t / 2
    return classify(s)


def cb_surprise_score(expected_change_bps: float | None, actual_change_bps: float | None,
                      expected_tone: float | None, actual_tone: float | None) -> tuple[float | None, str]:
    """Central bank surprise score -100 (dovish) .. +100 (hawkish) (Section 11)."""
    parts, weights = [], []
    if expected_change_bps is not None and actual_change_bps is not None:
        parts.append(_clip((actual_change_bps - expected_change_bps) / 25))
        weights.append(0.6)
    if expected_tone is not None and actual_tone is not None:
        parts.append(_clip((actual_tone - expected_tone) / 50))
        weights.append(0.4)
    if not parts:
        return None, "Unknown (no expectation recorded)"
    s = round(100 * sum(p * w for p, w in zip(parts, weights)) / sum(weights), 1)
    if s >= 40:
        label = "Strong Hawkish Surprise"
    elif s >= 15:
        label = "Hawkish Surprise"
    elif s <= -40:
        label = "Strong Dovish Surprise"
    elif s <= -15:
        label = "Dovish Surprise"
    else:
        label = "In Line"
    return s, label


def divergence(base: dict, quote: dict) -> dict:
    """base/quote: {"code", "currency", "score", "rate", "expected_change_bps", "y2", "y10",
    "inflation", "growth", "unemployment", "direction"}"""
    def diff(k):
        a, b = base.get(k), quote.get(k)
        return None if a is None or b is None else round(a - b, 3)

    d = {"policy_score": diff("score"), "policy_rate": diff("rate"),
         "expected_change_bps": diff("expected_change_bps"), "yield_2y": diff("y2"), "yield_10y": diff("y10"),
         "inflation": diff("inflation"), "growth": diff("growth"), "unemployment": diff("unemployment")}
    pts = 0.0
    n = 0
    for k, scale in (("policy_score", 20), ("expected_change_bps", 50), ("yield_2y", 1.0), ("policy_rate", 1.5)):
        if d[k] is not None:
            pts += _clip(d[k] / scale)
            n += 1
    lean = pts / n if n else 0.0
    b, q = base.get("currency", "?"), quote.get("currency", "?")
    if lean > 0.2:
        impl = f"Supports {b} vs {q} (policy divergence favours {b})"
    elif lean < -0.2:
        impl = f"Supports {q} vs {b} (policy divergence favours {q})"
    else:
        impl = f"Neutral for {b}/{q} (no material policy divergence)"
    return {"differences": d, "lean": round(lean, 3), "implication": impl}
