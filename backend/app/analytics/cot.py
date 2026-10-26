"""COT positioning maths (pure functions).

Net = long minus short. The COT index places the latest net position within its range over a window:
0 = the most bearish reading in the window, 100 = the most bullish. Above 90 or below 10 = crowded.
"""
from __future__ import annotations


def net(rows: list[dict], side: str) -> list[float]:
    l, s = {"spec": ("ncl", "ncs"), "comm": ("cl", "cs"), "small": ("nrl", "nrs")}[side]
    return [(r.get(l) or 0) - (r.get(s) or 0) for r in rows]


def cot_index(values: list[float], window: int) -> float | None:
    w = values[-window:]
    if len(w) < min(window, 8):
        return None
    lo, hi = min(w), max(w)
    return 50.0 if hi == lo else round((w[-1] - lo) / (hi - lo) * 100, 1)


def signals(rows: list[dict], window: int = 52) -> list[dict]:
    """Plain-language flags for the latest week. `rows` oldest first."""
    out: list[dict] = []
    if len(rows) < 2:
        return out
    spec, comm = net(rows, "spec"), net(rows, "comm")
    idx = cot_index(spec, window)
    if idx is not None and idx >= 90:
        out.append({"kind": "crowded_long", "tone": "warn",
                    "text": f"Speculators are crowded long (COT index {idx:.0f}). Look for price to stall before fading it."})
    elif idx is not None and idx <= 10:
        out.append({"kind": "crowded_short", "tone": "warn",
                    "text": f"Speculators are crowded short (COT index {idx:.0f}). Look for price to firm before fading it."})
    cidx = cot_index(comm, window)
    if cidx is not None and (cidx >= 90 or cidx <= 10):
        side = "long" if cidx >= 90 else "short"
        out.append({"kind": f"comm_extreme_{side}", "tone": "info",
                    "text": f"Commercials (hedgers) are at a {window}-week extreme net {side} (index {cidx:.0f}); "
                            "in commodities this often happens near turning points."})
    changes = [b - a for a, b in zip(spec[:-1], spec[1:])]
    if len(changes) >= 8:
        recent = changes[-1]
        typical = sorted(abs(c) for c in changes[-window:])[int(len(changes[-window:]) * 0.9) - 1]
        if typical and abs(recent) >= typical:
            out.append({"kind": "big_change", "tone": "info",
                        "text": f"Unusually large weekly change in speculator net ({recent:+,.0f} contracts), "
                                "among the biggest 10% of the window."})
    px = [r.get("price") for r in rows]
    if len(rows) >= 9 and all(p is not None for p in px[-9:]):
        recent_px, recent_spec = px[-9:], spec[-9:]
        if recent_px[-1] >= max(recent_px) and recent_spec[-1] < recent_spec[-5]:
            out.append({"kind": "divergence_top", "tone": "warn",
                        "text": "Price is at an 8-week high while speculators have been cutting longs: the trend may be tiring."})
        if recent_px[-1] <= min(recent_px) and recent_spec[-1] > recent_spec[-5]:
            out.append({"kind": "divergence_bottom", "tone": "warn",
                        "text": "Price is at an 8-week low while speculators have been covering shorts: selling may be tiring."})
    if len(rows) >= 5 and px[-1] is not None and px[-5] is not None:
        oi_up = rows[-1]["oi"] > rows[-5]["oi"]
        p_up = px[-1] > px[-5]
        if p_up and oi_up:
            out.append({"kind": "oi_confirm", "tone": "ok", "text": "Price and open interest both rising over 4 weeks: new money is backing the move up."})
        elif p_up and not oi_up:
            out.append({"kind": "short_covering", "tone": "info", "text": "Price rising on falling open interest: the move looks like short covering."})
        elif not p_up and oi_up:
            out.append({"kind": "new_shorts", "tone": "info", "text": "Price falling on rising open interest: new short positions are building."})
    return out
