"""Top setups: five pillars combined into one score per asset (pure functions).

Each pillar scores the asset from -2 (strongly bearish) to +2 (strongly bullish). For a currency pair the
currency-level pillars are base minus quote, so a positive number favours the pair rising.

  central_bank  hawkish statements and markets pricing hikes = bullish currency              weight 30
  economic      inflation above target and data beating forecasts = more hikes = bullish     weight 25
  cot           speculators adding longs = bullish, but a crowded extreme is a warning       weight 15
  seasonality   how the asset usually moves this month and over the next two weeks          weight 15
  retail        contrarian: when most retail traders are long, lean short (and vice versa)  weight 15

Missing pillars are left out and the others scaled up; `coverage` says how much of the weight was available.
The score is -100..+100. Grades need both size and agreement between pillars.
"""
from __future__ import annotations

from dataclasses import dataclass, field

WEIGHTS = {"central_bank": 30, "economic": 25, "cot": 15, "seasonality": 15, "retail": 15}
LABELS = {"central_bank": "Central bank & rate expectations", "economic": "Economic data & inflation",
          "cot": "COT positioning", "seasonality": "Seasonality", "retail": "Retail sentiment"}


def clip(x: float, lim: float = 2.0) -> float:
    return max(-lim, min(lim, x))


def avg(xs: list[float | None]) -> float | None:
    v = [x for x in xs if x is not None]
    return sum(v) / len(v) if v else None


# ---------------------------------------------------------------- currency-level pillars

def central_bank_score(policy_score: float | None, implied_bps: float | None, prob_hike: float | None,
                       prob_cut: float | None) -> float | None:
    """Policy score (0-100, 50 neutral) and market pricing (12-month bps, hike vs cut odds)."""
    parts = []
    if policy_score is not None:
        parts.append(clip((policy_score - 50) / 20))
    if implied_bps is not None:
        parts.append(clip(implied_bps / 50))
    if prob_hike is not None and prob_cut is not None:
        parts.append(clip((prob_hike - prob_cut) / 40))
    a = avg(parts)
    return None if a is None else round(a, 2)


def economic_score(inflation: float | None, target: float | None, data_score: int | None,
                   data_rows: int | None) -> float | None:
    """Inflation vs the central bank's target, and the share of recent releases that surprised hawkishly."""
    parts = []
    if inflation is not None and target is not None:
        parts.append(clip((inflation - target) / 1.0))
    if data_score is not None and data_rows:
        parts.append(clip(data_score / max(3, data_rows) * 4))
    a = avg(parts)
    return None if a is None else round(a, 2)


def cot_score(index_52: float | None, index_4w_ago: float | None, spec_change: float | None) -> float | None:
    """Trend-following in the middle of the range; contrarian at extremes (crowded trades)."""
    if index_52 is None:
        return None
    if index_52 >= 90:
        return -1.0
    if index_52 <= 10:
        return 1.0
    s = (index_52 - 50) / 40
    if index_4w_ago is not None:
        s += clip((index_52 - index_4w_ago) / 30, 1)
    return round(clip(s), 2)


def retail_score(long_pct: float | None) -> float | None:
    """Contrarian: 75% long -> -1.25; 30% long -> +1.0."""
    if long_pct is None:
        return None
    return round(clip(-(long_pct - 50) / 20), 2)


def seasonality_score(month: dict | None, weeks: list[dict] | None) -> float | None:
    """This month's and the next two weeks' tendencies: win rate distance from 50%, signed by the average."""
    def one(st: dict | None) -> float | None:
        if not st or not st.get("n") or st["n"] < 5 or st.get("avg") is None:
            return None
        edge = (st["win_rate"] - 50) / 25  # 75% -> +1
        if (edge > 0) != (st["avg"] > 0):
            edge *= 0.3  # win rate and average disagree: weak
        return clip(edge)
    parts = [one(month)] + [one(w) for w in (weeks or [])[:2]]
    a = avg(parts)
    return None if a is None else round(a, 2)


# ---------------------------------------------------------------- combining

@dataclass
class Setup:
    asset: str
    pillars: dict = field(default_factory=dict)       # name -> score -2..2 (None if missing)
    score: float = 0.0                                 # -100..100
    direction: str = "NONE"                            # LONG | SHORT | NONE
    grade: str = "No setup"
    agreement: float = 0.0
    coverage: float = 0.0
    reasons: list = field(default_factory=list)
    against: list = field(default_factory=list)


def combine(asset: str, pillars: dict[str, float | None], notes: dict[str, str] | None = None) -> Setup:
    notes = notes or {}
    have = {k: v for k, v in pillars.items() if v is not None}
    w = sum(WEIGHTS[k] for k in have)
    if not have:
        return Setup(asset, pillars, grade="Not enough data")
    score = round(100 * sum(v / 2 * WEIGHTS[k] for k, v in have.items()) / w, 1)
    direction = "LONG" if score > 0 else "SHORT" if score < 0 else "NONE"
    strong = [v for v in have.values() if abs(v) >= 0.25]
    agree = sum(1 for v in strong if (v > 0) == (score > 0)) / len(strong) if strong else 0.0
    coverage = round(w / sum(WEIGHTS.values()), 2)
    a = abs(score)
    if coverage < 0.5:
        grade = "Not enough data"
    elif a >= 60 and agree >= 0.8 and coverage >= 0.7:
        grade = "A+"
    elif a >= 45 and agree >= 0.7:
        grade = "A"
    elif a >= 30 and agree >= 0.6:
        grade = "B"
    elif a >= 20:
        grade = "C"
    else:
        grade = "No setup"
    if grade in ("No setup", "Not enough data"):
        direction = "NONE"
    order = sorted(have.items(), key=lambda kv: -abs(kv[1]) * WEIGHTS[kv[0]])
    reasons = [notes.get(k, LABELS[k]) for k, v in order if score and (v > 0) == (score > 0) and abs(v) >= 0.25]
    against = [notes.get(k, LABELS[k]) for k, v in order if score and (v > 0) != (score > 0) and abs(v) >= 0.25]
    return Setup(asset, pillars, score, direction, grade, round(agree, 2), coverage, reasons[:4], against[:3])
