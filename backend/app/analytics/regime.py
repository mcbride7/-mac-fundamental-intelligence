"""Global macro regime engine (Section 34). Pure."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RegimeInputs:
    inflation_trend: float | None = None      # avg 6m change in headline inflation (pp) across majors
    inflation_gap: float | None = None        # avg inflation minus target (pp)
    growth_signal: float | None = None        # avg (PMI-50)/5 and GDP vs trend, -1..1
    negative_gdp_share: float | None = None   # share of majors with negative latest GDP
    equity_trend: float | None = None         # % vs 50-day average
    gold_trend: float | None = None           # %
    safe_haven_fx: float | None = None        # avg % move of JPY & CHF vs USD (positive = havens stronger)
    policy_score_change: float | None = None  # avg change in policy scores over ~3 months
    avg_policy_score: float | None = None
    risk_label: str | None = None              # from the risk sentiment score: Risk-On | Risk-Off | Neutral
    risk_score: float | None = None            # 0..100


@dataclass
class RegimeResult:
    primary: str
    secondary: str | None
    confidence: float
    signals: dict = field(default_factory=dict)
    explanation: list = field(default_factory=list)


def evaluate(inp: RegimeInputs) -> RegimeResult:
    sig: dict[str, str] = {}
    why: list[str] = []
    avail = 0
    if inp.inflation_trend is not None:
        avail += 1
        if inp.inflation_trend <= -0.2:
            sig["inflation"] = "Disinflationary"
            why.append(f"Inflation falling across major economies ({inp.inflation_trend:+.2f} pp over 6m)")
        elif inp.inflation_trend >= 0.2 and (inp.inflation_gap or 0) > 0:
            sig["inflation"] = "Inflationary"
            why.append(f"Inflation rising and above target ({inp.inflation_trend:+.2f} pp over 6m)")
        else:
            sig["inflation"] = "Stable inflation"
    if inp.growth_signal is not None:
        avail += 1
        if (inp.negative_gdp_share or 0) >= 0.5 or inp.growth_signal <= -0.6:
            sig["growth"] = "Recession"
            why.append("Growth indicators consistent with contraction in several economies")
        elif inp.growth_signal < -0.15:
            sig["growth"] = "Slowing Growth"
            why.append("Growth indicators below trend / PMIs below 50")
        elif inp.growth_signal > 0.15:
            sig["growth"] = "Growth"
            why.append("Growth indicators above trend")
        else:
            sig["growth"] = "Trend Growth"
    risk_votes = []
    if inp.risk_label in ("Risk-On", "Risk-Off", "Neutral"):
        avail += 1
        sig["risk"] = inp.risk_label if inp.risk_label != "Neutral" else "Neutral risk"
        if inp.risk_label != "Neutral":
            why.append(f"Risk sentiment {inp.risk_label} ({inp.risk_score:.0f}/100 on VIX, credit spreads, "
                       "stocks and FX)")
    use_votes = "risk" not in sig  # older, simpler signal when no risk sentiment score exists yet
    if inp.equity_trend is not None:
        risk_votes.append(1 if inp.equity_trend > 1 else -1 if inp.equity_trend < -1 else 0)
    if inp.safe_haven_fx is not None:
        risk_votes.append(-1 if inp.safe_haven_fx > 0.75 else 1 if inp.safe_haven_fx < -0.75 else 0)
    if inp.gold_trend is not None:
        risk_votes.append(-1 if inp.gold_trend > 3 else 0)
    if risk_votes and use_votes:
        avail += 1
        v = sum(risk_votes)
        if v >= 1:
            sig["risk"] = "Risk-On"
            why.append("Equities firm and safe havens soft")
        elif v <= -1:
            sig["risk"] = "Risk-Off"
            why.append("Safe havens bid / equities weak")
        else:
            sig["risk"] = "Neutral risk"
    if inp.policy_score_change is not None:
        avail += 1
        if inp.policy_score_change <= -5:
            sig["liquidity"] = "Liquidity Expansion"
            why.append("Central banks turning more dovish on average")
        elif inp.policy_score_change >= 5:
            sig["liquidity"] = "Liquidity Tightening"
            why.append("Central banks turning more hawkish on average")
    infl = sig.get("inflation")
    growth = sig.get("growth")
    if infl == "Inflationary" and growth in ("Slowing Growth", "Recession"):
        primary = "STAGFLATION"
    elif growth == "Recession":
        primary = "RECESSION" + (" + DISINFLATION" if infl == "Disinflationary" else "")
    elif infl == "Disinflationary" and growth == "Slowing Growth":
        primary = "DISINFLATION + SLOWING GROWTH"
    elif infl == "Disinflationary" and growth in ("Growth", "Trend Growth"):
        primary = "DISINFLATIONARY GROWTH"
    elif infl == "Inflationary" and growth == "Growth":
        primary = "INFLATIONARY BOOM"
    elif infl == "Inflationary":
        primary = "INFLATIONARY"
    elif growth == "Growth":
        primary = "GROWTH"
    elif growth == "Slowing Growth":
        primary = "SLOWING GROWTH"
    else:
        primary = "NEUTRAL"
    secondary = sig.get("risk") if sig.get("risk") in ("Risk-On", "Risk-Off") else sig.get("liquidity")
    if secondary:
        secondary = secondary.upper()
    conf = round(min(95.0, 30 + 16 * avail), 1)
    if primary == "NEUTRAL":
        conf = min(conf, 50.0)
    if not why:
        why.append("Insufficient data to identify a clear regime")
    return RegimeResult(primary, secondary, conf, sig, why)
