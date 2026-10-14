"""Market intelligence (Sections 12, 30, 32): reactions, curves, repricing. Pure."""
from __future__ import annotations

from dataclasses import dataclass

WINDOWS_MIN = {"5m": 5, "30m": 30, "1h": 60, "eod": 480, "next_day": 1440, "1w": 10080}


def pct_change(before: float | None, after: float | None) -> float | None:
    if before in (None, 0) or after is None:
        return None
    return round((after / before - 1) * 100, 3)


def bps_change(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return round((after - before) * 100, 1)


def expected_reaction(currency: str, direction: str, symbols: list[str]) -> dict[str, int]:
    """Expected sign of the move per asset after a hawkish/dovish surprise for `currency`.
    +1 = up, -1 = down, 0 = unclear."""
    if direction not in ("Hawkish", "Dovish"):
        return {s: 0 for s in symbols}
    sgn = 1 if direction == "Hawkish" else -1
    out: dict[str, int] = {}
    for s in symbols:
        if len(s) == 6 and s.isalpha() and currency in (s[:3], s[3:]):
            out[s] = sgn if s.startswith(currency) else -sgn
        elif s.startswith(f"{currency_country(currency)}") and s.endswith("Y"):
            out[s] = sgn  # local yields rise on hawkish news
        elif s in ("XAUUSD", "XAGUSD") and currency == "USD":
            out[s] = -sgn
        elif s in ("SPX", "BTCUSD"):
            out[s] = -sgn if currency == "USD" else 0
        else:
            out[s] = 0
    return out


def currency_country(ccy: str) -> str:
    return {"USD": "US", "EUR": "DE", "GBP": "GB", "JPY": "JP", "CHF": "CH", "CAD": "CA", "AUD": "AU",
            "NZD": "NZ", "ZAR": "ZA", "MXN": "MX", "CNY": "CN"}.get(ccy, ccy[:2])


def divergences(windows: dict[str, dict[str, float | None]], expected: dict[str, int],
                min_move: dict[str, float] | None = None) -> list[dict]:
    """Assets that moved against the expected direction (by the 30m/1h window)."""
    min_move = min_move or {}
    out = []
    for w in ("30m", "1h", "eod"):
        moves = windows.get(w) or {}
        for sym, exp in expected.items():
            mv = moves.get(sym)
            if exp == 0 or mv is None:
                continue
            thr = min_move.get(sym, 2.0 if sym.endswith("Y") else 0.05)
            if abs(mv) >= thr and (mv > 0) != (exp > 0):
                out.append({"window": w, "symbol": sym, "expected": "up" if exp > 0 else "down",
                            "actual": mv, "note": f"{sym} moved {'up' if mv > 0 else 'down'} {abs(mv)}"
                                                  f"{' bps' if sym.endswith('Y') else '%'} against expectations"})
        if out:
            break
    return out


def explain_divergence(div: list[dict], already_priced: bool | None, risk_regime: str | None) -> list[str]:
    reasons = []
    if not div:
        return reasons
    if already_priced:
        reasons.append("The outcome appears to have been largely priced in beforehand ('buy the rumour, sell "
                       "the fact').")
    if risk_regime and "Risk-Off" in risk_regime:
        reasons.append("Broader risk-off flows may be dominating the reaction to this single event.")
    reasons.append("Other simultaneous releases or positioning may explain the move; check same-time events.")
    return reasons


@dataclass
class Curve:
    points: dict
    slope_2s10s_bps: float | None
    shape: str | None


def curve(points: dict[str, float]) -> Curve:
    s = None
    shape = None
    if "2Y" in points and "10Y" in points:
        s = round((points["10Y"] - points["2Y"]) * 100, 1)
        shape = "INVERTED" if s < -10 else ("FLAT" if s < 25 else "NORMAL")
    return Curve(points, s, shape)


def repricing(before: dict | None, after: dict | None) -> dict | None:
    """before/after: {prob_cut, prob_hold, prob_hike, implied_change_bps}"""
    if not before or not after:
        return None
    d = {k: round((after.get(k) or 0) - (before.get(k) or 0), 1) for k in ("prob_cut", "prob_hold", "prob_hike")}
    net = d["prob_hike"] - d["prob_cut"]
    if net >= 15:
        label = "Hawkish repricing"
    elif net >= 5:
        label = "Modest hawkish repricing"
    elif net <= -15:
        label = "Dovish repricing"
    elif net <= -5:
        label = "Modest dovish repricing"
    else:
        label = "No material repricing"
    text = (f"Cut probability {before.get('prob_cut', 0):.0f}% → {after.get('prob_cut', 0):.0f}%, "
            f"hold {before.get('prob_hold', 0):.0f}% → {after.get('prob_hold', 0):.0f}%, "
            f"hike {before.get('prob_hike', 0):.0f}% → {after.get('prob_hike', 0):.0f}%. {label}.")
    return {"changes": d, "net_hawkish_shift": round(net, 1), "label": label, "explanation": text}


def implied_change_proxy(y2: float | None, policy_rate: float | None) -> float | None:
    """When no OIS/futures data is available: 2Y yield minus policy rate (bps) is a rough
    proxy for the expected policy path over the next 1-2 years. Labelled as a proxy."""
    if y2 is None or policy_rate is None:
        return None
    return round((y2 - policy_rate) * 100, 0)
