"""Supply & demand engine: the user's own strategy (SD_Strategy/code/sd_strategy.py), vendored unchanged.

Only the parts the site needs are kept: parameters and presets, zone detection, the bar-by-bar backtester
(confirmation entries, conservative fills) and the live fresh-zone list. The command-line tool, metrics,
walk-forward and data loaders stay in the original project. Rules: SD_Strategy/RULES_OF_ENGAGEMENT.md.
Do not edit the logic here; change the original and copy it again so backtests and the site agree.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Parameters
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Params:
    atr_len: int = 14
    # base candles
    base_max_body_ratio: float = 0.5
    base_max_range_atr: float = 1.0
    base_min_bars: int = 1
    base_max_bars: int = 5
    # leg-out candle
    legout_min_range_atr: float = 1.5
    legout_min_body_ratio: float = 0.6
    # zone quality
    max_zone_width_atr: float = 1.5
    zone_max_age: int = 200
    # trade management
    trend_ema: int = 200
    stop_buffer_atr: float = 0.1
    reward_risk: float = 2.0
    max_hold_bars: int = 100
    allow_short: bool = True
    # money management and frictions
    risk_per_trade: float = 0.01
    max_leverage: float = 2.0
    commission_bps: float = 1.0
    slippage_bps: float = 1.0
    # volume (thresholds of 0 / inf disable a filter)
    vol_len: int = 20
    legout_min_rvol: float = 1.5
    base_max_rvol: float = 1.0
    approach_max_rvol: float = float("inf")
    approach_bars: int = 1           # average RVOL over this many candles before the touch
    reject_min_rvol: float = 0.0     # confirm mode: rejection candle needs at least this RVOL
    # Fibonacci premium/discount. Dealing range = zone far edge -> furthest price reached
    # after the zone formed (before the return). Retracement 0.5 = equilibrium.
    fib_min_retrace: float = 0.0     # zone near edge must be at least this deep (0.5 = discount)
    fib_entry_min: float = 0.0       # the actual entry price must be at least this deep
    # order-block rules (from the "order blocks" video)
    ob_engulf: bool = False          # last candle before the leg-out is the opposite colour
                                     # (last sell candle before the buy) and gets engulfed
    manip_sweep: bool = False        # the zone's own low (demand) / high (supply) swept an
                                     # untaken swing low/high first: the "fake move"
    manip_lookback: int = 30         # how far back that swing may be (candles)
    manip_k: int = 3                 # swing = extreme of manip_k candles either side
    latest_only: bool = False        # a newer zone of the same side cancels older ones
    entry_depth: float = 0.0         # zone counts as tapped only this deep (0.5 = its 50%)
    require_fvg: bool = False        # imbalance: the candle after the leg-out must leave a
                                     # wick-to-wick gap beyond the base (zone valid from then on)
    # VWAP
    vwap_mode: str = "auto"          # "auto" | "rolling" | "session" | "off"
    vwap_len: int = 20               # bars, rolling mode
    vwap_filter: str = "discount"    # "off" | "discount" | "trend" | "both"
    vwap_slope_bars: int = 5
    # entry and stop placement
    entry_mode: str = "limit"        # "limit" = resting order at zone | "confirm" = wait for rejection close
    confirm_bars: int = 3            # confirm mode: bars allowed after the touch to get a rejection close
    min_stop_atr: float = 0.0        # minimum stop distance in ATR (0 = zone-based stop only)
    # market structure: zone only valid once its move breaks the last swing point
    require_bos: bool = False        # supply must break the prior swing low, demand the prior swing high
    pivot_k: int = 2                 # swing point = extreme of k bars either side
    bos_max_bars: int = 30           # bars allowed after the leg-out for the break to happen
    # liquidity
    liq_k: int = 3                   # swing = extreme of liq_k bars either side (liquidity pools)
    inducement: bool = False         # a swing low (demand) / high (supply) formed in front of the zone
                                     # after it was created, and price ran it on the way into the zone
    zone_sweep: bool = False         # confirm mode: the touch wicked THROUGH the zone (stop hunt below
                                     # demand / above supply) and still closed back out of it
    target_mode: str = "fixed"       # "fixed" = reward_risk x R | "liquidity" = nearest untaken swing
    liq_min_rr: float = 1.5          # liquidity target must be at least this many R away
    liq_max_rr: float = 5.0          # ... and is capped here
    liq_lookback: int = 300          # bars back to look for untaken swing highs/lows
    # "don't be the liquidity": keep the stop beyond untaken swing lows/highs near the zone
    stop_beyond_liq: bool = False
    liq_beyond_atr: float = 1.0      # look for untaken swings up to this far beyond the zone
    liq_stop_buffer: float = 0.3     # stop goes this many ATR beyond such a swing
    max_stop_atr: float = 4.0        # skip the trade if that makes the stop wider than this
    # origin of the move: the zone's base must be the extreme of the recent swing
    origin_lookback: int = 0         # bars before the base that must all be above (demand) /
                                     # below (supply) the zone (0 = off)
    protected_only: bool = False     # needs require_bos: the zone must be the protected low/high,
                                     # i.e. the extreme between the broken swing and the break


IMPROVED = dict(entry_mode="confirm", min_stop_atr=1.0, reward_risk=2.0,
                legout_min_range_atr=1.2, base_max_range_atr=1.2, max_zone_width_atr=2.0, zone_max_age=500)


# Best on USTEC 4-hour 2016-2021, confirmed on 2022-2026: improved + volume + break of structure
H4_BEST = dict(IMPROVED, legout_min_rvol=1.2, base_max_rvol=1.0,
               require_bos=True, pivot_k=3, bos_max_bars=60)


def baseline(p: Params) -> Params:
    """The original strategy: same zones and exits, no VWAP or volume filters."""
    return replace(p, legout_min_rvol=0.0, base_max_rvol=float("inf"),
                   approach_max_rvol=float("inf"), vwap_filter="off")


@dataclass
class Zone:
    kind: str          # "demand" | "supply"
    proximal: float
    distal: float
    created: int       # index of the leg-out bar (tradable from created + 1)
    base_len: int
    strength: float    # leg-out range / ATR
    pattern: str       # e.g. "drop-base-rally"
    legout_rvol: float = float("nan")
    base_rvol: float = float("nan")
    active_from: int = -1            # bar at whose close the zone becomes tradable (-1 = created)
    bos_level: float = float("nan")


# --------------------------------------------------------------------------- #
# Indicators
# --------------------------------------------------------------------------- #
def atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["Close"].shift(1)
    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def has_volume(df: pd.DataFrame) -> bool:
    return "Volume" in df.columns and bool((df["Volume"].fillna(0) > 0).mean() > 0.9)


def relative_volume(df: pd.DataFrame, n: int) -> np.ndarray | None:
    """Volume / mean volume of the PREVIOUS n bars."""
    if not has_volume(df):
        return None
    v = df["Volume"].astype(float)
    return (v / v.rolling(n, min_periods=n).mean().shift(1)).to_numpy()


def is_intraday(index: pd.Index) -> bool:
    return (isinstance(index, pd.DatetimeIndex) and len(index) > 2
            and pd.Series(index).diff().median() < pd.Timedelta(hours=20))


def vwap(df: pd.DataFrame, p: Params) -> np.ndarray | None:
    """Rolling VWAP (daily+ bars) or session VWAP reset each calendar day (intraday)."""
    if p.vwap_mode == "off" or not has_volume(df):
        return None
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    v = df["Volume"].astype(float)
    pv = tp * v
    mode = p.vwap_mode if p.vwap_mode != "auto" else ("session" if is_intraday(df.index) else "rolling")
    if mode == "session":
        day = df.index.normalize()
        return (pv.groupby(day).cumsum() / v.groupby(day).cumsum()).to_numpy()
    n = p.vwap_len
    return (pv.rolling(n, min_periods=n).sum() / v.rolling(n, min_periods=n).sum()).to_numpy()


def vwap_ok(side: int, proximal: float, vw: np.ndarray | None, t: int, p: Params) -> bool:
    """VWAP filter evaluated with data up to bar t-1."""
    if vw is None or p.vwap_filter == "off":
        return True
    v = vw[t - 1]
    if not np.isfinite(v):
        return False
    if p.vwap_filter in ("discount", "both"):
        if (side == 1 and proximal > v) or (side == -1 and proximal < v):
            return False
    if p.vwap_filter in ("trend", "both"):
        k = t - 1 - p.vwap_slope_bars
        if k < 0 or not np.isfinite(vw[k]):
            return False
        if (side == 1 and v <= vw[k]) or (side == -1 and v >= vw[k]):
            return False
    return True


# --------------------------------------------------------------------------- #
# Zone detection
# --------------------------------------------------------------------------- #
def detect_zones(df: pd.DataFrame, p: Params) -> tuple[list[Zone], np.ndarray, np.ndarray | None]:
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    a = atr(df, p.atr_len).to_numpy()
    rv = relative_volume(df, p.vol_len)
    rng = h - l
    body = np.abs(c - o)
    br = np.divide(body, rng, out=np.zeros_like(body), where=rng > 0)
    is_base = (br <= p.base_max_body_ratio) & (rng <= p.base_max_range_atr * np.nan_to_num(a, nan=np.inf))

    piv_lo = piv_hi = []
    if p.require_bos:
        k = p.pivot_k
        lo_s, hi_s = pd.Series(l), pd.Series(h)
        piv_lo = list(np.where(lo_s == lo_s.rolling(2 * k + 1, center=True).min())[0])
        piv_hi = list(np.where(hi_s == hi_s.rolling(2 * k + 1, center=True).max())[0])

    mk_lo = mk_hi = np.array([], dtype=int)
    if p.manip_sweep:
        km = p.manip_k
        lo_s, hi_s = pd.Series(l), pd.Series(h)
        mk_lo = np.where(lo_s == lo_s.rolling(2 * km + 1, center=True).min())[0]
        mk_hi = np.where(hi_s == hi_s.rolling(2 * km + 1, center=True).max())[0]

    zones: list[Zone] = []
    for i in range(p.atr_len + p.base_max_bars + 1, len(df)):
        ref = a[i - 1]
        if not np.isfinite(ref) or ref <= 0:
            continue
        if rng[i] < p.legout_min_range_atr * ref or br[i] < p.legout_min_body_ratio:
            continue

        # walk back over base candles
        n, j = 0, i - 1
        while j >= 0 and is_base[j] and n < p.base_max_bars:
            n, j = n + 1, j - 1
        if n < p.base_min_bars or (j >= 0 and is_base[j]):   # too short / consolidation too long
            continue
        b0 = i - n
        if b0 < 1:
            continue

        base_hi, base_lo = h[b0:i].max(), l[b0:i].min()
        body_top = np.maximum(o[b0:i], c[b0:i]).max()
        body_bot = np.minimum(o[b0:i], c[b0:i]).min()
        leg_in = "rally" if c[b0 - 1] > o[b0 - 1] else "drop"

        if c[i] > o[i] and c[i] > base_hi:
            kind, prox, dist, pat = "demand", body_top, min(base_lo, l[i]), f"{leg_in}-base-rally"
        elif c[i] < o[i] and c[i] < base_lo:
            kind, prox, dist, pat = "supply", body_bot, max(base_hi, h[i]), f"{leg_in}-base-drop"
        else:
            continue

        width = abs(prox - dist)
        if width <= 0 or width > p.max_zone_width_atr * ref:
            continue
        if p.ob_engulf:
            # demand: the last candle before the leg-out is bearish (and the leg-out closes
            # above its high, already true); supply: bullish last candle
            if kind == "demand" and not c[i - 1] < o[i - 1]:
                continue
            if kind == "supply" and not c[i - 1] > o[i - 1]:
                continue
        if p.manip_sweep:
            # the fake move: the leg-in (up to 3 candles before the base) or the base itself
            # takes out an untaken swing low (demand) / high (supply) formed before it
            km = p.manip_k
            ws = max(0, b0 - 3)
            ext = l[ws:i + 1].min() if kind == "demand" else h[ws:i + 1].max()
            piv = mk_lo if kind == "demand" else mk_hi
            js = piv[(piv + km <= ws) & (piv >= ws - p.manip_lookback)]
            swept = False
            for jj in js:
                lvl = l[jj] if kind == "demand" else h[jj]
                if jj + 1 < ws:
                    untaken = (l[jj + 1:ws].min() > lvl) if kind == "demand" else (h[jj + 1:ws].max() < lvl)
                else:
                    untaken = True
                if untaken and ((kind == "demand" and ext < lvl) or (kind == "supply" and ext > lvl)):
                    swept = True; break
            if not swept:
                continue
        if p.origin_lookback > 0:
            w0 = max(0, b0 - p.origin_lookback)
            if kind == "demand" and l[w0:b0].min() < dist:
                continue                  # an earlier low is lower: this base is mid-move
            if kind == "supply" and h[w0:b0].max() > dist:
                continue

        lo_rv = base_rv = float("nan")
        if rv is not None:
            lo_rv = float(rv[i])
            seg = rv[b0:i][np.isfinite(rv[b0:i])]
            base_rv = float(seg.mean()) if len(seg) else float("nan")
            if p.legout_min_rvol > 0 and not (np.isfinite(lo_rv) and lo_rv >= p.legout_min_rvol):
                continue
            if np.isfinite(p.base_max_rvol) and not (np.isfinite(base_rv) and base_rv <= p.base_max_rvol):
                continue
        z = Zone(kind, float(prox), float(dist), i, n, float(rng[i] / ref), pat, lo_rv, base_rv, i)
        if p.require_fvg:
            if i + 1 >= len(df):
                continue
            gap = (l[i + 1] > base_hi) if kind == "demand" else (h[i + 1] < base_lo)
            if not gap:
                continue
            z.active_from = i + 1         # the imbalance is only known at the close of i+1
        if p.require_bos:
            # last swing low (supply) / swing high (demand) confirmed before the base started
            k = p.pivot_k
            piv = piv_lo if kind == "supply" else piv_hi
            cand = [j for j in piv if j + k <= b0 and j < b0]
            if not cand:
                continue
            j = cand[-1]
            level = l[j] if kind == "supply" else h[j]
            z.bos_level = float(level)
            act = None
            for t in range(i, min(i + p.bos_max_bars + 1, len(df))):
                if t > i and ((kind == "supply" and h[t] >= prox) or (kind == "demand" and l[t] <= prox)):
                    break                     # came back to the zone before breaking structure -> invalid
                if (kind == "supply" and c[t] < level) or (kind == "demand" and c[t] > level):
                    act = t; break
            if act is None:
                continue
            if p.protected_only:
                # demand: nothing between the broken swing high and the break went below the zone
                if kind == "demand" and l[j:act + 1].min() < dist - 1e-9:
                    continue
                if kind == "supply" and h[j:act + 1].max() > dist + 1e-9:
                    continue
            z.active_from = max(act, z.active_from)
        zones.append(z)
    return zones, a, rv


# --------------------------------------------------------------------------- #
# Backtest engine
# --------------------------------------------------------------------------- #
def backtest(df: pd.DataFrame, p: Params, start_equity: float = 100_000.0,
             trade_start: int = 0) -> tuple[pd.Series, pd.DataFrame]:
    """Bar-by-bar simulation. Returns (equity curve, trades)."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    idx = df.index
    zones, a, rv = detect_zones(df, p)
    vw = vwap(df, p)
    trend = ema(df["Close"], p.trend_ema).to_numpy() if p.trend_ema else None
    by_bar: dict[int, list[Zone]] = {}
    for z in zones:
        by_bar.setdefault(z.active_from if z.active_from >= 0 else z.created, []).append(z)

    # liquidity pools: swing highs/lows, usable from bar j + liq_k (confirmation) onwards
    kq = p.liq_k
    hs, ls = pd.Series(h), pd.Series(l)
    sw_hi = np.where(hs == hs.rolling(2 * kq + 1, center=True).max())[0]
    sw_lo = np.where(ls == ls.rolling(2 * kq + 1, center=True).min())[0]

    def has_inducement(z: Zone, t: int) -> bool:
        """Swing formed after the zone, in front of it, confirmed before the touch bar t."""
        piv = sw_lo if z.kind == "demand" else sw_hi
        js = piv[(piv > z.created) & (piv + kq <= t - 1)]
        if z.kind == "demand":
            return bool(np.any(l[js] > z.proximal))
        return bool(np.any(h[js] < z.proximal))

    def fib_retrace(z: Zone, t: int, price: float) -> float:
        """How deep `price` sits in the leg from the zone's far edge to the furthest
        point reached since the zone formed (bars created..t-1). 1 = at the far edge."""
        if t <= z.created:
            return 0.0
        if z.kind == "demand":
            top = h[z.created:t].max(); rng_ = top - z.distal
            return (top - price) / rng_ if rng_ > 0 else 0.0
        bot = l[z.created:t].min(); rng_ = z.distal - bot
        return (price - bot) / rng_ if rng_ > 0 else 0.0

    def liquidity_target(t: int, side: int, fill: float, risk: float) -> float:
        """Nearest swing high (long) / low (short) not yet taken out, >= liq_min_rr away."""
        piv = sw_hi if side == 1 else sw_lo
        js = piv[(piv + kq <= t - 1) & (piv >= t - p.liq_lookback)][::-1]   # most recent first
        best = None
        for j in js:
            lvl = h[j] if side == 1 else l[j]
            if (lvl - fill) * side < p.liq_min_rr * risk:
                continue
            seg = slice(j + 1, t)
            taken = (h[seg].max() >= lvl) if side == 1 else (l[seg].min() <= lvl)
            if taken:
                continue
            if best is None or (lvl - best) * side < 0:
                best = lvl
        if best is None:
            return fill + side * p.reward_risk * risk
        return min(best, fill + p.liq_max_rr * risk) if side == 1 else max(best, fill - p.liq_max_rr * risk)

    comm, slip = p.commission_bps / 1e4, p.slippage_bps / 1e4
    equity = start_equity
    eq = np.full(len(df), start_equity, dtype=float)
    active: list[Zone] = []
    pos: dict | None = None
    trades: list[dict] = []

    def close(t: int, px: float, reason: str):
        nonlocal equity, pos
        side = pos["side"]
        fill = px * (1 - slip) if side == 1 else px * (1 + slip)
        gross = side * pos["qty"] * (fill - pos["entry"])
        fee = pos["qty"] * fill * comm
        equity += gross - fee
        net = gross - fee - pos["entry_fee"]
        trades.append({
            "entry_time": idx[pos["bar"]], "exit_time": idx[t], "side": "long" if side == 1 else "short",
            "pattern": pos["zone"].pattern, "entry": pos["entry"], "exit": fill, "stop": pos["stop"],
            "target": pos["target"], "qty": pos["qty"], "pnl": net,
            "R": net / (pos["qty"] * pos["risk_unit"]), "bars": t - pos["bar"], "reason": reason,
            "zone_strength": pos["zone"].strength, "legout_rvol": pos["zone"].legout_rvol,
            "zone_kind": pos["zone"].kind, "zone_prox": pos["zone"].proximal, "zone_dist": pos["zone"].distal,
            "zone_base_time": idx[pos["zone"].created - pos["zone"].base_len], "zone_created_time": idx[pos["zone"].created],
            "zone_active_time": idx[pos["zone"].active_from if pos["zone"].active_from >= 0 else pos["zone"].created],
            "bos_level": pos["zone"].bos_level,
            "base_rvol": pos["zone"].base_rvol, "approach_rvol": pos["approach_rvol"],
            "vwap_dist_atr": pos["vwap_dist_atr"],   # >0 = entered at a discount (long) / premium (short)
        })
        pos = None

    armed: list[dict] = []
    pending = None

    def open_pos(t: int, z: Zone, side: int, raw: float, stop: float):
        nonlocal equity, pos
        fill = raw * (1 + slip) if side == 1 else raw * (1 - slip)
        if p.fib_entry_min > 0 and fib_retrace(z, t, fill) < p.fib_entry_min:
            return
        if p.stop_beyond_liq:
            ref_a = a[t - 1]
            piv = sw_lo if side == 1 else sw_hi
            js = piv[(piv + kq <= t - 1) & (piv >= t - p.liq_lookback)]
            for j in js:
                lvl = l[j] if side == 1 else h[j]
                near = (z.distal - p.liq_beyond_atr * ref_a <= lvl <= z.distal + 0.05 * ref_a) if side == 1 \
                    else (z.distal - 0.05 * ref_a <= lvl <= z.distal + p.liq_beyond_atr * ref_a)
                if not near:
                    continue
                taken = (l[j + 1:t].min() < lvl) if side == 1 else (h[j + 1:t].max() > lvl)
                if not taken:             # resting stops still there -> put ours beyond them
                    stop = min(stop, lvl - p.liq_stop_buffer * ref_a) if side == 1 \
                        else max(stop, lvl + p.liq_stop_buffer * ref_a)
            if abs(fill - stop) > p.max_stop_atr * ref_a:
                return
        if p.min_stop_atr > 0:                       # never put the stop inside normal daily noise
            floor = p.min_stop_atr * a[t - 1]
            stop = min(stop, fill - floor) if side == 1 else max(stop, fill + floor)
        risk_unit = (fill - stop) * side
        if risk_unit <= 0 or equity <= 0:
            return
        qty = min(equity * p.risk_per_trade / risk_unit, equity * p.max_leverage / fill)
        fee = qty * fill * comm
        equity -= fee
        target = (liquidity_target(t, side, fill, risk_unit) if p.target_mode == "liquidity"
                  else fill + side * p.reward_risk * risk_unit)
        pos = {"side": side, "qty": qty, "entry": fill, "stop": stop,
               "target": target, "risk_unit": risk_unit,
               "bar": t, "zone": z, "entry_fee": fee,
               "approach_rvol": float(rv[t - 1]) if rv is not None else float("nan"),
               "vwap_dist_atr": (float(side * (vw[t - 1] - fill) / a[t - 1])
                                 if vw is not None and np.isfinite(vw[t - 1]) else float("nan"))}
        # conservative: stop can hit on the entry bar, target cannot
        if (side == 1 and l[t] <= stop) or (side == -1 and h[t] >= stop):
            close(t, stop, "stop_entry_bar")

    for t in range(1, len(df)):
        flat_at_open = pos is None

        # 1) manage open position --------------------------------------------
        if pos is not None:
            s, st, tg = pos["side"], pos["stop"], pos["target"]
            if s == 1:
                if o[t] <= st:   close(t, o[t], "stop_gap")
                elif l[t] <= st: close(t, st, "stop")
                elif o[t] >= tg: close(t, o[t], "target_gap")
                elif h[t] >= tg: close(t, tg, "target")
            else:
                if o[t] >= st:   close(t, o[t], "stop_gap")
                elif h[t] >= st: close(t, st, "stop")
                elif o[t] <= tg: close(t, o[t], "target_gap")
                elif l[t] <= tg: close(t, tg, "target")
            if pos is not None and t - pos["bar"] >= p.max_hold_bars:
                close(t, c[t], "time")

        # 2) zone touches -> entries (fresh zones only) ------------------------
        # 2a) confirmation mode: execute the signal confirmed at the previous close
        if pending is not None:
            z, side, stop = pending
            pending = None
            if flat_at_open and pos is None:
                open_pos(t, z, side, o[t], stop)

        def tap(z):    # price level that counts as a tap (zone edge, or deeper with entry_depth)
            return z.proximal + p.entry_depth * (z.distal - z.proximal)
        touched = [z for z in active
                   if (z.kind == "demand" and l[t] <= tap(z)) or (z.kind == "supply" and h[t] >= tap(z))]
        cands = []
        if flat_at_open and t >= trade_start and touched:
            for z in touched:
                long_ = z.kind == "demand"
                if not long_ and not p.allow_short:
                    continue
                if trend is not None:
                    if not np.isfinite(trend[t - 1]):
                        continue
                    if long_ and c[t - 1] <= trend[t - 1]:
                        continue
                    if not long_ and c[t - 1] >= trend[t - 1]:
                        continue
                if not vwap_ok(1 if long_ else -1, z.proximal, vw, t, p):
                    continue
                if rv is not None and np.isfinite(p.approach_max_rvol):
                    seg = rv[max(0, t - p.approach_bars):t]
                    seg = seg[np.isfinite(seg)]
                    if not (len(seg) and seg.mean() <= p.approach_max_rvol):
                        continue
                if p.inducement and not has_inducement(z, t):
                    continue
                if p.fib_min_retrace > 0 and fib_retrace(z, t, z.proximal) < p.fib_min_retrace:
                    continue
                cands.append(z)

        if p.entry_mode == "limit":
            if cands and pos is None:
                z = min(cands, key=lambda z: abs(o[t] - z.proximal))   # first zone price meets
                side = 1 if z.kind == "demand" else -1
                buf = p.stop_buffer_atr * a[t - 1]
                stop = z.distal - buf if side == 1 else z.distal + buf
                raw = min(o[t], tap(z)) if side == 1 else max(o[t], tap(z))
                open_pos(t, z, side, raw, stop)
        else:
            # 2b) confirmation mode: arm touched zones, wait for a rejection close
            if pos is None:
                for z in cands:
                    armed.append({"z": z, "touch": t, "ext": l[t] if z.kind == "demand" else h[t]})
            still = []
            for ar in armed:
                z = ar["z"]; side = 1 if z.kind == "demand" else -1
                ar["ext"] = min(ar["ext"], l[t]) if side == 1 else max(ar["ext"], h[t])
                broken = c[t] < z.distal if side == 1 else c[t] > z.distal
                if broken or t - ar["touch"] > p.confirm_bars or pos is not None:
                    continue
                rejected = (c[t] > z.proximal and c[t] > o[t]) if side == 1 else (c[t] < z.proximal and c[t] < o[t])
                if rejected and p.reject_min_rvol > 0 and rv is not None:
                    rejected = bool(np.isfinite(rv[t]) and rv[t] >= p.reject_min_rvol)
                if rejected and p.zone_sweep:
                    rejected = ar["ext"] < z.distal if side == 1 else ar["ext"] > z.distal
                if rejected and pending is None:
                    buf = p.stop_buffer_atr * a[t]
                    stop = min(z.distal, ar["ext"]) - buf if side == 1 else max(z.distal, ar["ext"]) + buf
                    pending = (z, side, stop)
                    continue
                still.append(ar)
            armed = still if pending is None else []

        if touched:                                   # any touch consumes a zone (freshness rule)
            gone = {id(z) for z in touched}
            active = [z for z in active if id(z) not in gone]

        # 3) register new zones and expire old ones ----------------------------
        new = by_bar.get(t, [])
        if p.latest_only and new:
            kinds = {z.kind for z in new}
            active = [z for z in active if z.kind not in kinds]
        active.extend(new)
        active = [z for z in active if t - z.created <= p.zone_max_age]

        # 4) mark to market --------------------------------------------------------
        eq[t] = equity + (pos["side"] * pos["qty"] * (c[t] - pos["entry"]) if pos else 0.0)

    if pos is not None:
        close(len(df) - 1, c[-1], "end_of_data")
        eq[-1] = equity
    return pd.Series(eq, index=idx, name="equity"), pd.DataFrame(trades)


def live_orders(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Replays zone consumption to the last bar and returns the fresh zones as
    limit orders. Run on each new bar close and push the result to your broker
    (cancel/replace). Size each order with risk_per_trade at execution time."""
    zones, a, rv = detect_zones(df, p)
    vw = vwap(df, p)
    h, l, c = df["High"].to_numpy(), df["Low"].to_numpy(), df["Close"].to_numpy()
    trend = ema(df["Close"], p.trend_ema).to_numpy() if p.trend_ema else None
    by_bar: dict[int, list[Zone]] = {}
    for z in zones:
        by_bar.setdefault(z.active_from if z.active_from >= 0 else z.created, []).append(z)
    active: list[Zone] = []
    for t in range(1, len(df)):
        active = [z for z in active if not ((z.kind == "demand" and l[t] <= z.proximal) or
                                            (z.kind == "supply" and h[t] >= z.proximal))]
        active.extend(by_bar.get(t, []))
        active = [z for z in active if t - z.created <= p.zone_max_age]

    last = len(df) - 1
    rows = []
    for z in active:
        side = 1 if z.kind == "demand" else -1
        if side == -1 and not p.allow_short:
            continue
        if trend is not None and np.isfinite(trend[last]):
            if (side == 1 and c[last] <= trend[last]) or (side == -1 and c[last] >= trend[last]):
                continue
        if not vwap_ok(side, z.proximal, vw, last + 1, p):
            continue
        stop = z.distal - side * p.stop_buffer_atr * a[last]
        risk = abs(z.proximal - stop)
        rows.append({"side": "BUY_LIMIT" if side == 1 else "SELL_LIMIT", "limit": z.proximal,
                     "stop": stop, "target": z.proximal + side * p.reward_risk * risk,
                     "pattern": z.pattern, "zone_created": df.index[z.created],
                     "strength": round(z.strength, 2), "legout_rvol": round(z.legout_rvol, 2),
                     "vwap": round(float(vw[last]), 4) if vw is not None else None,
                     "approach_ok": (rv is None or not np.isfinite(p.approach_max_rvol)
                                     or bool(rv[last] <= p.approach_max_rvol)),
                     "distance_atr": round(abs(c[last] - z.proximal) / a[last], 2)})
    return pd.DataFrame(rows).sort_values("distance_atr") if rows else pd.DataFrame()
