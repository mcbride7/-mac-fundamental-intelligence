"""Currency fundamental scores and heatmap (Sections 35, 46). Pure."""
from __future__ import annotations

from dataclasses import dataclass, field

SAFE_HAVENS = {"JPY": 1.0, "CHF": 1.0, "USD": 0.5}
RISK_CURRENCIES = {"AUD": 1.0, "NZD": 1.0, "ZAR": 1.0, "MXN": 1.0, "CAD": 0.5, "GBP": 0.3, "EUR": 0.2,
                   "CNY": 0.3}


@dataclass
class CurrencyInputs:
    currency: str
    policy_score: float | None = None          # 0..100
    policy_rate: float | None = None
    avg_policy_rate: float | None = None       # across the universe
    implied_change_bps: float | None = None
    inflation: float | None = None
    inflation_target: float | None = None
    inflation_vs_projection: float | None = None
    growth_vs_projection: float | None = None
    gdp_latest: float | None = None
    pmi: float | None = None
    unemployment_change_6m: float | None = None
    y2: float | None = None
    y2_change_1m_bps: float | None = None
    avg_y2: float | None = None
    surprise_index: float | None = None
    risk_regime: str | None = None             # "Risk-On" | "Risk-Off" | None
    evidence_quality: float = 100.0


@dataclass
class CurrencyScoreResult:
    currency: str
    components: dict = field(default_factory=dict)
    total: float = 0.0
    bias: str = "NEUTRAL"
    coverage: float = 0.0
    notes: list = field(default_factory=list)


def _r(x: float) -> float:
    """Round to the nearest integer in -3..+3 (the score scale shown in the UI)."""
    return float(max(-3, min(3, round(x))))


def score(inp: CurrencyInputs) -> CurrencyScoreResult:
    c: dict[str, float] = {}
    notes = []
    g = []
    if inp.growth_vs_projection is not None:
        g.append(inp.growth_vs_projection / 0.3)
    if inp.pmi is not None:
        g.append((inp.pmi - 50) / 1.5)
    if inp.gdp_latest is not None and not g:
        g.append((inp.gdp_latest - 1.5) / 0.7)
    if g:
        c["growth"] = _r(sum(g) / len(g))
    inf = []
    if inp.inflation is not None and inp.inflation_target is not None:
        gap = inp.inflation - inp.inflation_target
        # inflation above target pushes the bank hawkish (currency supportive) — but runaway
        # inflation (>4 pp over target) erodes the currency, so the score fades back.
        inf.append(gap / 0.5 if gap <= 4 else (8 - gap) / 0.5)
    if inp.inflation_vs_projection is not None:
        inf.append(inp.inflation_vs_projection / 0.25)
    if inf:
        c["inflation"] = _r(sum(inf) / len(inf))
    if inp.unemployment_change_6m is not None:
        c["employment"] = _r(-inp.unemployment_change_6m / 0.15)
    if inp.policy_score is not None:
        c["central_bank"] = _r((inp.policy_score - 50) / 12)
    rates = []
    if inp.policy_rate is not None and inp.avg_policy_rate is not None:
        rates.append((inp.policy_rate - inp.avg_policy_rate) / 1.0)
    if inp.implied_change_bps is not None:
        rates.append(inp.implied_change_bps / 40)
    if rates:
        c["interest_rates"] = _r(sum(rates) / len(rates))
    yl = []
    if inp.y2 is not None and inp.avg_y2 is not None:
        yl.append((inp.y2 - inp.avg_y2) / 1.0)
    if inp.y2_change_1m_bps is not None:
        yl.append(inp.y2_change_1m_bps / 15)
    if yl:
        c["bond_yields"] = _r(sum(yl) / len(yl))
    if inp.surprise_index is not None:
        c["economic_surprises"] = _r(inp.surprise_index / 0.4)
    if inp.risk_regime in ("Risk-On", "Risk-Off"):
        sign = 1 if inp.risk_regime == "Risk-Off" else -1
        if inp.currency in SAFE_HAVENS:
            c["risk_sentiment"] = _r(sign * 2 * SAFE_HAVENS[inp.currency])
        elif inp.currency in RISK_CURRENCIES:
            c["risk_sentiment"] = _r(-sign * 2 * RISK_CURRENCIES[inp.currency])
        else:
            c["risk_sentiment"] = 0.0
    total = sum(c.values())
    max_total = 3 * len(c) if c else 1
    if total >= max(4, 0.25 * max_total):
        bias = "BULLISH"
    elif total <= -max(4, 0.25 * max_total):
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"
    coverage = len(c) / 8
    if coverage < 0.5:
        notes.append(f"Only {len(c)} of 8 components available — treat with caution")
    return CurrencyScoreResult(inp.currency, c, total, bias, round(coverage, 2), notes)


def heatmap(totals: dict[str, float]) -> dict:
    ccys = list(totals)
    rows = {}
    for a in ccys:
        rows[a] = {}
        for b in ccys:
            if a == b:
                rows[a][b] = {"symbol": "—", "diff": 0}
                continue
            d = totals[a] - totals[b]
            sym = "++" if d >= 8 else "+" if d >= 3 else "--" if d <= -8 else "-" if d <= -3 else "="
            rows[a][b] = {"symbol": sym, "diff": round(d, 1)}
    return {"currencies": ccys, "matrix": rows}
