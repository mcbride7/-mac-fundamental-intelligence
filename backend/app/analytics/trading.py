"""Trade confluence, grading and the NO-TRADE engine (Sections 39-41, 60-62). Pure.

The output is decision support, never a signal to execute: every setup carries
its drivers, confirmation, invalidation and risks, and the system prefers
NO TRADE whenever evidence is insufficient or conflicting."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.enums import Grade

FACTOR_WEIGHTS = {
    "central_bank_divergence": 20, "rate_differential": 18, "inflation_differential": 12,
    "growth_differential": 10, "yield_differential": 12, "economic_surprise": 8, "risk_sentiment": 5,
    "employment_differential": 5, "forecast_deviation": 5, "positioning": 5,
}
LABELS = {
    "central_bank_divergence": "Central Bank Divergence", "rate_differential": "Rate Differential",
    "inflation_differential": "Inflation Differential", "growth_differential": "Growth Differential",
    "yield_differential": "Yield Differential", "economic_surprise": "Economic Surprise",
    "risk_sentiment": "Risk Sentiment", "employment_differential": "Employment Differential",
    "forecast_deviation": "Forecast Deviation", "positioning": "Positioning",
}


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))


@dataclass
class Side:
    """Fundamental inputs for one currency of the pair."""
    currency: str
    cb_code: str | None = None
    policy_score: float | None = None
    policy_confidence: float | None = None
    policy_rate: float | None = None
    implied_change_bps: float | None = None
    inflation_gap: float | None = None
    growth_component: float | None = None   # currency score growth component (-3..3)
    employment_component: float | None = None
    y2: float | None = None
    y2_change_1m_bps: float | None = None
    surprise_index: float | None = None
    risk_component: float | None = None
    forecast_deviation: float | None = None  # policy-implication score from projections
    positioning: float | None = None         # net speculative positioning z-score (CFTC), if available


@dataclass
class Confluence:
    factors: dict = field(default_factory=dict)      # name -> signed points (favouring base)
    unavailable: list = field(default_factory=list)
    total: float = 0.0                                 # -100..100, + favours base (asset up)
    direction: str = "NONE"                            # LONG | SHORT | NONE
    agreement: float = 0.0
    conviction: float = 0.0


def confluence(base: Side, quote: Side) -> Confluence:
    f: dict[str, float] = {}
    unavailable: list[str] = []

    def add(name: str, value: float | None) -> None:
        if value is None:
            unavailable.append(name)
        else:
            f[name] = round(_clip(value) * FACTOR_WEIGHTS[name], 1)

    def d(a, b):
        return None if a is None or b is None else a - b

    ps = d(base.policy_score, quote.policy_score)
    add("central_bank_divergence", None if ps is None else ps / 30)
    rd = d(base.policy_rate, quote.policy_rate)
    ed = d(base.implied_change_bps, quote.implied_change_bps)
    parts = [x for x in ((rd / 2.0) if rd is not None else None, (ed / 75) if ed is not None else None)
             if x is not None]
    add("rate_differential", sum(parts) / len(parts) if parts else None)
    ig = d(base.inflation_gap, quote.inflation_gap)
    add("inflation_differential", None if ig is None else ig / 2.0)
    gd = d(base.growth_component, quote.growth_component)
    add("growth_differential", None if gd is None else gd / 4)
    yl = d(base.y2, quote.y2)
    yc = d(base.y2_change_1m_bps, quote.y2_change_1m_bps)
    parts = [x for x in ((yl / 2.0) if yl is not None else None, (yc / 30) if yc is not None else None)
             if x is not None]
    add("yield_differential", sum(parts) / len(parts) if parts else None)
    sd = d(base.surprise_index, quote.surprise_index)
    add("economic_surprise", None if sd is None else sd / 1.0)
    rk = d(base.risk_component, quote.risk_component)
    add("risk_sentiment", None if rk is None else rk / 4)
    em = d(base.employment_component, quote.employment_component)
    add("employment_differential", None if em is None else em / 4)
    fd = d(base.forecast_deviation, quote.forecast_deviation)
    add("forecast_deviation", None if fd is None else fd / 1.5)
    pos = d(base.positioning, quote.positioning)
    # crowded long base positioning is a headwind for further base strength
    add("positioning", None if pos is None else -pos / 3)
    avail_max = sum(FACTOR_WEIGHTS[k] for k in f) or 1
    total = round(100 * sum(f.values()) / avail_max, 1) if f else 0.0
    direction = "LONG" if total > 0 else "SHORT" if total < 0 else "NONE"
    nz = [v for v in f.values() if abs(v) >= 1]
    agree = (sum(1 for v in nz if (v > 0) == (total > 0)) / len(nz)) if nz else 0.0
    conviction = round(abs(total) * (0.6 + 0.4 * agree), 1)
    return Confluence(f, unavailable, total, direction, round(agree, 2), conviction)


def grade(total: float, agreement: float) -> Grade:
    a = abs(total)
    if a >= 75 and agreement >= 0.8:
        return Grade.A_PLUS
    if a >= 60 and agreement >= 0.7:
        return Grade.A
    if a >= 45:
        return Grade.B
    if a >= 30:
        return Grade.C
    return Grade.NO_TRADE


@dataclass
class NoTradeInputs:
    pending_events: list = field(default_factory=list)  # [{"name", "hours_until", "importance"}]
    conflict: bool = False
    base_policy_confidence: float | None = None
    quote_policy_confidence: float | None = None
    scenario_gap: float | None = None                    # base prob minus strongest opposite prob (pp)
    price_move_20d_pct: float | None = None             # asset move over ~20 trading days
    evidence_quality: float = 100.0
    available_factors: int = 0


def no_trade_reasons(c: Confluence, inp: NoTradeInputs) -> list[str]:
    r: list[str] = []
    if inp.conflict:
        r.append("Data conflicts: critical data is in CONFLICT with the official source")
    imminent = [e for e in inp.pending_events if e.get("hours_until") is not None and 0 <= e["hours_until"] <= 24
                and e.get("importance") == "high"]
    if imminent:
        e = imminent[0]
        r.append(f"Important data is pending: {e['name']} in {e['hours_until']:.0f}h")
    if (inp.base_policy_confidence is not None and inp.base_policy_confidence < 35) or \
            (inp.quote_policy_confidence is not None and inp.quote_policy_confidence < 35):
        r.append("Central-bank policy is unclear (low policy-score confidence)")
    yf = c.factors.get("yield_differential")
    if yf is not None and c.direction != "NONE" and abs(yf) >= 6 and (yf > 0) != (c.direction == "LONG"):
        r.append("Bond market contradicts the FX thesis (yield differential points the other way)")
    if inp.scenario_gap is not None and inp.scenario_gap < 10:
        r.append(f"Scenario probabilities are too balanced (gap {inp.scenario_gap:.0f} pp)")
    if inp.price_move_20d_pct is not None and c.direction != "NONE":
        moved_with = (inp.price_move_20d_pct > 0) == (c.direction == "LONG")
        if moved_with and abs(inp.price_move_20d_pct) >= 3.0:
            r.append(f"Market may already price the thesis (asset moved {inp.price_move_20d_pct:+.1f}% in 20 days)")
    if inp.evidence_quality < 45:
        r.append(f"Forecast/evidence uncertainty is high (evidence quality {inp.evidence_quality:.0f}/100)")
    if inp.available_factors < 4:
        r.append(f"Too few independent factors available ({inp.available_factors}); confluence cannot be assessed")
    if abs(c.total) < 30:
        r.append(f"Confluence too weak ({c.total:+.0f}/100) — factors do not agree strongly enough")
    return r
