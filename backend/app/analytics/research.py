"""Advanced research analytics (Phase 7): historical analogues, conditional
returns, forecast rankings and the "Is the market wrong?" engine. Pure."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

DISCLAIMER = "Historical results describe past episodes only and are not a guarantee of future outcomes."


def conditional_returns(event_times: list[datetime], prices: list[tuple[datetime, float]],
                        horizons_days: tuple[int, ...] = (1, 5, 20)) -> dict:
    """Average % change of a price series after each event time."""
    if not prices:
        return {"n": 0, "horizons": {}, "note": "No price history available"}
    prices = sorted(prices)
    times = [t for t, _ in prices]

    def at(t: datetime) -> float | None:
        import bisect

        i = bisect.bisect_right(times, t) - 1
        return prices[i][1] if i >= 0 else None

    out = {}
    for h in horizons_days:
        rets = []
        for et in event_times:
            p0, p1 = at(et), at(et + timedelta(days=h))
            if p0 and p1 and et + timedelta(days=h) <= times[-1]:
                rets.append((p1 / p0 - 1) * 100)
        if rets:
            out[f"{h}d"] = {"n": len(rets), "mean_pct": round(statistics.fmean(rets), 3),
                            "median_pct": round(statistics.median(rets), 3),
                            "hit_rate_up": round(sum(1 for r in rets if r > 0) / len(rets), 2)}
    return {"n": len(event_times), "horizons": out, "disclaimer": DISCLAIMER}


@dataclass
class StatePoint:
    when: datetime
    vector: dict  # feature -> value


def analogues(current: dict, history: list[StatePoint], k: int = 5) -> list[dict]:
    """Nearest historical states (standardised Euclidean distance). Similarity 0-100."""
    feats = [f for f in current if current[f] is not None and sum(1 for h in history if h.vector.get(f)
                                                                     is not None) >= 3]
    if not feats or not history:
        return []
    stats = {}
    for f in feats:
        vals = [h.vector[f] for h in history if h.vector.get(f) is not None]
        stats[f] = (statistics.fmean(vals), statistics.pstdev(vals) or 1.0)
    scored = []
    for h in history:
        common = [f for f in feats if h.vector.get(f) is not None]
        if len(common) < max(2, len(feats) // 2):
            continue
        d2 = sum(((current[f] - h.vector[f]) / stats[f][1]) ** 2 for f in common) / len(common)
        sim = 100 * math.exp(-math.sqrt(d2))
        scored.append({"when": h.when, "similarity": round(sim, 1), "state": h.vector, "features": common})
    scored.sort(key=lambda x: -x["similarity"])
    # avoid returning clustered neighbouring months
    picked: list[dict] = []
    for s in scored:
        if all(abs((s["when"] - p["when"]).days) > 60 for p in picked):
            picked.append(s)
        if len(picked) >= k:
            break
    return picked


def rank_forecasters(rows: list[dict]) -> list[dict]:
    """rows: [{"forecaster", "variable", "score", "n"}] -> ranking per variable and overall."""
    by_f: dict[str, list[float]] = {}
    for r in rows:
        if r.get("n", 0) >= 3:
            by_f.setdefault(r["forecaster"], []).append(r["score"])
    ranking = [{"forecaster": f, "overall": round(statistics.fmean(s), 1), "variables": len(s)}
               for f, s in by_f.items()]
    ranking.sort(key=lambda x: -x["overall"])
    for i, r in enumerate(ranking, 1):
        r["rank"] = i
    return ranking


def market_wrong(cb_code: str, implication_score: float | None, policy_score: float | None,
                 prob_cut: float | None, prob_hike: float | None, implied_12m_bps: float | None,
                 inflation_vs_projection: float | None) -> dict | None:
    """Detect disconnects between economic reality and market pricing (Section 33).
    Returns a research alert (never a trade) or None."""
    hawk_reality = 0.0
    n = 0
    if implication_score is not None:
        hawk_reality += max(-1, min(1, implication_score))
        n += 1
    if policy_score is not None:
        hawk_reality += (policy_score - 50) / 25
        n += 1
    if inflation_vs_projection is not None:
        hawk_reality += max(-1, min(1, inflation_vs_projection / 0.5))
        n += 1
    if not n:
        return None
    reality = hawk_reality / n
    pricing = None
    if implied_12m_bps is not None:
        pricing = max(-1, min(1, implied_12m_bps / 75))
    elif prob_cut is not None and prob_hike is not None:
        pricing = max(-1, min(1, (prob_hike - prob_cut) / 50))
    if pricing is None:
        return None
    gap = reality - pricing
    if gap >= 0.8 and reality > 0.2 and pricing < 0:
        return {"central_bank": cb_code, "type": "hawkish_repricing_risk", "gap": round(gap, 2),
                "title": f"{cb_code}: potential hawkish repricing risk",
                "body": "Data and policy signals lean hawkish, but rates markets price easing. "
                        "If the data persist, markets may need to price fewer cuts. Research alert only — "
                        "not a trade signal."}
    if gap <= -0.8 and reality < -0.2 and pricing > 0:
        return {"central_bank": cb_code, "type": "dovish_repricing_risk", "gap": round(gap, 2),
                "title": f"{cb_code}: potential dovish repricing risk",
                "body": "Data and policy signals lean dovish, but rates markets price tightening. "
                        "Markets may need to price a more dovish path. Research alert only — not a trade signal."}
    return None
