"""Scenario engine (Sections 37-38). Pure.

Probabilities come from the confluence total (net evidence) and the risk
regime, through an explicit, documented formula — so they are transparent and
reproducible rather than invented."""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Trigger:
    trigger_type: str  # activation | confirmation | invalidation
    description: str
    metric: str | None = None
    operator: str | None = None
    threshold: float | None = None

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ScenarioOut:
    kind: str  # base | bullish | bearish | risk
    title: str
    narrative: str
    direction: str  # up | down | flat
    probability: float
    drivers: list = field(default_factory=list)
    triggers: list = field(default_factory=list)
    evidence: list = field(default_factory=list)


@dataclass
class ScenarioContext:
    asset: str
    base_ccy: str
    quote_ccy: str
    base_cb: str | None
    quote_cb: str | None
    confluence_total: float
    factors: dict
    regime_secondary: str | None = None
    metrics: dict = field(default_factory=dict)   # metric key -> current value
    catalysts: list = field(default_factory=list)  # [{"name", "date", "currency"}]


def probabilities(total: float, risk_off: bool) -> dict:
    """base/aligned-extension/opposite/risk split. Formula documented in the guide."""
    risk = 0.20 if risk_off else 0.12
    p_dir = 0.5 + 0.35 * math.tanh(abs(total) / 40)
    rest = 1 - risk
    base = p_dir * rest * 0.75
    ext = p_dir * rest * 0.25
    opp = (1 - p_dir) * rest
    vals = {"base": base, "extension": ext, "opposite": opp, "risk": risk}
    rounded = {k: round(v * 100) for k, v in vals.items()}
    drift = 100 - sum(rounded.values())
    rounded["base"] += drift
    return rounded


def _top(factors: dict, sign: int, n: int = 3) -> list[str]:
    from app.analytics.trading import LABELS

    items = sorted(((k, v) for k, v in factors.items() if v * sign > 0), key=lambda kv: -abs(kv[1]))
    return [f"{LABELS.get(k, k)} ({v:+.0f})" for k, v in items[:n]]


def _metric_triggers(ctx: ScenarioContext, up: bool) -> tuple[list[Trigger], list[Trigger]]:
    """Confirmation / invalidation conditions for a move in direction `up` of the asset."""
    m = ctx.metrics
    conf, inv = [], []
    b, q = ctx.base_cb, ctx.quote_cb
    bc, qc = ctx.base_ccy, ctx.quote_ccy
    strong, weak = (b, q) if up else (q, b)
    strong_ccy, weak_ccy = (bc, qc) if up else (qc, bc)
    if strong and f"POLICY:{strong}" in m:
        v = m[f"POLICY:{strong}"]
        conf.append(Trigger("confirmation", f"{strong} policy score stays at or above {v - 5:.0f} (now {v:.0f})",
                            f"POLICY:{strong}", ">=", round(v - 5, 1)))
        inv.append(Trigger("invalidation", f"{strong} turns materially more dovish (policy score below {v - 15:.0f})",
                           f"POLICY:{strong}", "<", round(v - 15, 1)))
    if weak and f"POLICY:{weak}" in m:
        v = m[f"POLICY:{weak}"]
        conf.append(Trigger("confirmation", f"{weak} policy score stays at or below {v + 5:.0f} (now {v:.0f})",
                            f"POLICY:{weak}", "<=", round(v + 5, 1)))
        inv.append(Trigger("invalidation", f"{weak} turns materially more hawkish (policy score above {v + 15:.0f})",
                           f"POLICY:{weak}", ">", round(v + 15, 1)))
    key = f"SPREAD2Y:{bc}-{qc}"
    if key in m:
        v = m[key]
        if up:
            conf.append(Trigger("confirmation", f"{bc}–{qc} 2Y spread holds above {v - 0.15:.2f} pp (now {v:.2f})",
                                key, ">=", round(v - 0.15, 3)))
            inv.append(Trigger("invalidation", f"{bc}–{qc} 2Y spread falls below {v - 0.40:.2f} pp", key, "<",
                               round(v - 0.40, 3)))
        else:
            conf.append(Trigger("confirmation", f"{bc}–{qc} 2Y spread stays below {v + 0.15:.2f} pp (now {v:.2f})",
                                key, "<=", round(v + 0.15, 3)))
            inv.append(Trigger("invalidation", f"{bc}–{qc} 2Y spread rises above {v + 0.40:.2f} pp", key, ">",
                               round(v + 0.40, 3)))
    for ccy, hawkish_good in ((strong_ccy, True), (weak_ccy, False)):
        k = f"INFL:{ccy}"
        if k in m:
            v = m[k]
            if hawkish_good:
                inv.append(Trigger("invalidation", f"{ccy} inflation falls sharply (below {v - 0.5:.1f}%, now "
                                                   f"{v:.1f}%)", k, "<", round(v - 0.5, 2)))
            else:
                inv.append(Trigger("invalidation", f"{ccy} inflation re-accelerates (above {v + 0.5:.1f}%, now "
                                                   f"{v:.1f}%)", k, ">", round(v + 0.5, 2)))
    return conf, inv


def build(ctx: ScenarioContext) -> list[ScenarioOut]:
    risk_off = (ctx.regime_secondary or "").upper() == "RISK-OFF"
    p = probabilities(ctx.confluence_total, risk_off)
    up_base = ctx.confluence_total >= 0
    b, q = ctx.base_cb or ctx.base_ccy, ctx.quote_cb or ctx.quote_ccy
    asset = ctx.asset

    def scen(kind: str, up: bool, prob: float, title: str, narrative: str, drivers: list[str]) -> ScenarioOut:
        if kind == "risk":
            act = [Trigger("activation", "A growth, credit or geopolitical shock hits global risk appetite")]
            conf = [Trigger("confirmation", "Equities fall sharply while JPY, CHF and gold rally"),
                    Trigger("confirmation", "Credit spreads widen and volatility jumps")]
            inv = [Trigger("invalidation", "Risk assets stabilise and safe havens give back their gains")]
            return ScenarioOut(kind, title, narrative, "up" if up else "down", prob, drivers,
                               [t.as_dict() for t in act + conf + inv], [])
        conf, inv = _metric_triggers(ctx, up)
        act = [Trigger("activation", c["name"] + (f" ({c['date']})" if c.get("date") else ""))
               for c in ctx.catalysts[:3]]
        return ScenarioOut(kind, title, narrative, "up" if up else "down", prob, drivers,
                           [t.as_dict() for t in act + conf + inv],
                           [{"factor": k, "points": v} for k, v in ctx.factors.items()])

    favoured, other = (ctx.base_ccy, ctx.quote_ccy) if up_base else (ctx.quote_ccy, ctx.base_ccy)
    fav_cb, oth_cb = (b, q) if up_base else (q, b)
    base_drivers = _top(ctx.factors, 1 if up_base else -1)
    opp_drivers = _top(ctx.factors, -1 if up_base else 1)
    base = scen("base", up_base, p["base"],
                f"{fav_cb} relatively more hawkish than {oth_cb}; {favoured} outperforms",
                f"Base case: the current fundamental differential persists. {', '.join(base_drivers) or 'Mixed evidence'}"
                f" favour {favoured}. {asset} {'rises' if up_base else 'falls'}.", base_drivers)
    ext = scen("bullish" if up_base else "bearish", up_base, p["extension"],
               f"Divergence widens further — {asset} {'extends higher' if up_base else 'extends lower'}",
               f"Data surprises in favour of {favoured} (or a policy shift by {oth_cb}) accelerate the existing trend.",
               base_drivers)
    opp = scen("bearish" if up_base else "bullish", not up_base, p["opposite"],
               f"{oth_cb} turns more hawkish or {fav_cb} more dovish — {asset} "
               f"{'falls' if up_base else 'rises'}",
               f"Alternative: the differential narrows. {', '.join(opp_drivers) or 'A reversal in recent data'} "
               f"would support {other}.", opp_drivers)
    risk_up = ctx.quote_ccy in ("USD", "JPY", "CHF") and ctx.base_ccy not in ("JPY", "CHF")
    risk = scen("risk", not risk_up, p["risk"], "Global risk-off shock",
                "Risk scenario: a growth or financial shock triggers flight to safety (JPY, CHF, USD, gold). "
                f"{asset} {'falls' if risk_up else 'rises'} regardless of the policy differential.",
                ["Safe-haven demand"])
    return [base, ext, opp, risk]


def evaluate_trigger(t: dict, metrics: dict) -> str:
    m, op, th = t.get("metric"), t.get("operator"), t.get("threshold")
    if not m or op is None or th is None or m not in metrics:
        return "pending"
    v = metrics[m]
    ok = {">": v > th, ">=": v >= th, "<": v < th, "<=": v <= th}.get(op, False)
    return "met" if ok else "not_met"
