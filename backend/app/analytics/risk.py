"""Risk-on / risk-off sentiment (pure functions).

Eight market signals are each scored from -100 (extreme fear, risk-off) to +100 (extreme confidence,
risk-on), then averaged with weights into one 0-100 score:  >= 60 Risk-On, <= 40 Risk-Off, else Neutral.

  vix            VIX vs its own past year (high = fear)                          weight 0.22
  credit         US high-yield bond spread vs its past year (wide = fear)        weight 0.20
  equities       S&P 500 vs its 50-day average                                    weight 0.14
  audjpy         AUD/JPY 20-day change (the classic risk barometer)               weight 0.12
  safe_havens    JPY and CHF strength over 20 days (strong havens = fear)         weight 0.10
  em_fx          ZAR and MXN strength over 20 days (weak EM FX = fear)            weight 0.10
  gold_vs_stocks S&P 500 minus gold over 20 days (gold winning = fear)            weight 0.07
  bonds          10-year yield and stocks over 20 days (both falling = flight to safety)  weight 0.05

Signals with too little data are left out and the weights of the rest are scaled up; `coverage` says how
much of the full weight was available.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

WEIGHTS = {"vix": 0.22, "credit": 0.20, "equities": 0.14, "audjpy": 0.12, "safe_havens": 0.10,
           "em_fx": 0.10, "gold_vs_stocks": 0.07, "bonds": 0.05}
LABELS = {"vix": "VIX (fear index)", "credit": "High-yield credit spreads", "equities": "S&P 500 trend",
          "audjpy": "AUD/JPY", "safe_havens": "Safe havens (JPY, CHF)", "em_fx": "Emerging-market FX (ZAR, MXN)",
          "gold_vs_stocks": "Gold vs stocks", "bonds": "Bonds and stocks"}
RISK_ON, RISK_OFF = 60.0, 40.0
YEAR, TREND, MOVE = 252, 50, 20


@dataclass
class Component:
    key: str
    label: str
    score: float      # -100..+100
    reading: str      # what was measured, in words
    weight: float


@dataclass
class RiskResult:
    score: float | None             # 0..100
    label: str                      # Risk-On | Risk-Off | Neutral | No data
    components: list[Component] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    coverage: float = 0.0           # share of total weight available, 0..1
    divergence: bool = False
    notes: list[str] = field(default_factory=list)


def _clamp(x: float, lim: float = 100.0) -> float:
    return max(-lim, min(lim, x))


def _pct_change(vals: list[float], n: int) -> float | None:
    if len(vals) <= n or vals[-1 - n] == 0:
        return None
    return (vals[-1] / vals[-1 - n] - 1) * 100


def _z_vs_year(vals: list[float]) -> float | None:
    hist = vals[-YEAR:]
    if len(hist) < 60:
        return None
    sd = statistics.pstdev(hist)
    if sd == 0:
        return None
    return (vals[-1] - statistics.fmean(hist)) / sd


def evaluate(series: dict[str, list[float]]) -> RiskResult:
    """`series`: daily values, oldest first, keyed vix, hy_oas, spx, usdjpy, usdchf, audusd, usdzar, usdmxn,
    gold, us10y. Any may be missing or short."""
    s = {k: [v for v in vals if v is not None] for k, vals in series.items()}
    comps: list[Component] = []

    def add(key: str, score: float | None, reading: str):
        if score is not None:
            comps.append(Component(key, LABELS[key], round(_clamp(score), 1), reading, WEIGHTS[key]))

    vix = s.get("vix", [])
    z = _z_vs_year(vix)
    if z is not None:
        add("vix", -z / 2.0 * 100, f"VIX {vix[-1]:.1f} ({z:+.1f} standard deviations vs its past year)")
    oas = s.get("hy_oas", [])
    z = _z_vs_year(oas)
    if z is not None:
        add("credit", -z / 2.0 * 100, f"Spread {oas[-1]:.2f}% ({z:+.1f} standard deviations vs its past year)")
    spx = s.get("spx", [])
    if len(spx) >= TREND:
        ma = statistics.fmean(spx[-TREND:])
        gap = (spx[-1] / ma - 1) * 100
        add("equities", gap / 5 * 100, f"S&P 500 {gap:+.1f}% vs its 50-day average")
    aud, jpy = s.get("audusd", []), s.get("usdjpy", [])
    n = min(len(aud), len(jpy))
    if n > MOVE:
        cross = [a * j for a, j in zip(aud[-n:], jpy[-n:])]
        ch = _pct_change(cross, MOVE)
        add("audjpy", ch / 3 * 100, f"AUD/JPY {cross[-1]:.2f}, {ch:+.1f}% over 20 days")
    havens = [c for c in (_pct_change(s.get("usdjpy", []), MOVE), _pct_change(s.get("usdchf", []), MOVE))
              if c is not None]
    if havens:
        strength = -statistics.fmean(havens)  # USD/JPY falling = yen stronger
        add("safe_havens", -strength / 2 * 100, f"JPY and CHF {strength:+.1f}% vs USD over 20 days")
    em = [c for c in (_pct_change(s.get("usdzar", []), MOVE), _pct_change(s.get("usdmxn", []), MOVE)) if c is not None]
    if em:
        strength = -statistics.fmean(em)
        add("em_fx", strength / 3 * 100, f"ZAR and MXN {strength:+.1f}% vs USD over 20 days")
    gold = s.get("gold", [])
    sp, gd = _pct_change(spx, MOVE), _pct_change(gold, MOVE)
    if sp is not None and gd is not None:
        add("gold_vs_stocks", (sp - gd) / 5 * 100, f"S&P 500 {sp:+.1f}% vs gold {gd:+.1f}% over 20 days")
    y10 = s.get("us10y", [])
    if sp is not None and len(y10) > MOVE:
        dy = (y10[-1] - y10[-1 - MOVE]) * 100
        add("bonds", (dy / 25 + sp / 3) / 2 * 100, f"10-year yield {dy:+.0f} bp, S&P 500 {sp:+.1f}% over 20 days")

    missing = [LABELS[k] for k in WEIGHTS if k not in {c.key for c in comps}]
    total_w = sum(c.weight for c in comps)
    if not comps:
        return RiskResult(None, "No data", [], missing, 0.0, False, ["No market data yet"])
    raw = sum(c.score * c.weight for c in comps) / total_w
    score = round(50 + raw / 2, 1)
    label = "Risk-On" if score >= RISK_ON else "Risk-Off" if score <= RISK_OFF else "Neutral"
    strong_on = [c.label for c in comps if c.score >= 30]
    strong_off = [c.label for c in comps if c.score <= -30]
    divergence = bool(strong_on and strong_off) and min(len(strong_on), len(strong_off)) >= 1 and \
        (len(strong_on) + len(strong_off)) >= 3
    notes = []
    if divergence:
        notes.append(f"Signals disagree: {', '.join(strong_on)} point to risk-on but {', '.join(strong_off)} "
                     "point to risk-off. Sentiment may be about to turn.")
    coverage = round(total_w / sum(WEIGHTS.values()), 2)
    if coverage < 0.6:
        notes.append(f"Only {coverage:.0%} of the signals have enough data, so treat this reading with care.")
    return RiskResult(score, label, sorted(comps, key=lambda c: -c.weight), missing, coverage, divergence, notes)


FX_IMPLICATION = {
    "Risk-On": "Risk-on usually helps AUD, NZD, ZAR, MXN and stocks, and weighs on JPY, CHF and gold.",
    "Risk-Off": "Risk-off usually strengthens JPY, CHF, USD and gold, and weighs on AUD, NZD, ZAR, MXN and stocks.",
    "Neutral": "No strong risk mood: currencies are likely to follow their own data and central banks.",
    "No data": "",
}
