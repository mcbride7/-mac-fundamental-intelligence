"""The user's supply & demand strategy applied to the site's pairs (USTEC 4-hour Rules of Engagement).

Rules (SD_Strategy/RULES_OF_ENGAGEMENT.md, section A), run with the vendored engine unchanged:
- 4-hour candles (built from FMP's hourly bars), trend = 200-candle EMA (buys above, sells below)
- zone: 1-5 base candles, leg-out >= 1.2 ATR with a 60% body, break of structure within 60 candles,
  imbalance after the leg-out, zone <= 2 ATR wide, fresh (first return only), expires after 500 candles
- volume rules (quiet base, leg-out >= 1.2x volume) apply when the bars carry volume
- grade on the return: A+ = liquidity sweep in front of the zone; B = zone on the right side of the
  20-candle VWAP (needs volume); otherwise no trade
- entry: a 4-hour close back out of the zone within 3 candles, at the next open (no limit orders)
- stop beyond the far edge / touch extreme + 0.1 ATR, at least 1 ATR; target 2R; time stop 100 candles
"""
from __future__ import annotations

import time as _time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.strategy import sd_engine as e

RULES = "USTEC 4-hour Rules of Engagement"
MIN_CANDLES = 260  # the 200 EMA needs 200; a little extra so zones can form
_CACHE: dict = {}


def params() -> e.Params:
    return replace(e.baseline(e.Params()), **e.H4_BEST, require_fvg=True)


def candles_4h(db: Session, symbol: str) -> pd.DataFrame:
    """4-hour candles (UTC 00/04/08/...) from the stored hourly bars."""
    from app.ingestion.fmp_bars import bars

    rows = bars(db, symbol, "1hour")
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame([{"ts": b.ts, "Open": b.open, "High": b.high, "Low": b.low, "Close": b.close,
                        "Volume": b.volume} for b in rows]).set_index("ts").sort_index()
    df.index = pd.to_datetime(df.index, utc=True)
    out = df.resample("4h", origin="epoch", label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
    out = out.dropna(subset=["Open", "Close"])
    if not (out["Volume"].fillna(0) > 0).mean() > 0.9:
        out = out.drop(columns=["Volume"])  # no real volume: the engine switches the volume rules off
    return out


def _stamp(db: Session, symbol: str) -> tuple:
    """Cheap check for new or changed hourly bars (one aggregate query)."""
    from sqlalchemy import func, select

    from app.models.track import PriceBar

    return tuple(db.execute(select(func.count(), func.max(PriceBar.ts), func.sum(PriceBar.close))
                            .where(PriceBar.symbol == symbol, PriceBar.interval == "1hour")).one())


def run(db: Session, symbol: str) -> dict:
    """Trades the rules took on this pair, the fresh zones still waiting, and the candles (cached until new bars)."""
    try:
        key = (symbol, _stamp(db, symbol))
    except Exception:
        key = None
    hit = _CACHE.get(symbol)
    if key is not None and hit and hit[0] == key and _time.time() - hit[1] < 3600:
        return hit[2]
    df = candles_4h(db, symbol)
    res = {"symbol": symbol, "candles": df, "trades": pd.DataFrame(), "zones": pd.DataFrame(),
           "has_volume": "Volume" in df.columns, "enough": len(df) >= MIN_CANDLES}
    if res["enough"]:
        p = params()
        _, sweep = e.backtest(df, replace(p, inducement=True))
        frames = [sweep.assign(grade="A+")] if len(sweep) else []
        if res["has_volume"]:
            _, vw = e.backtest(df, replace(p, vwap_filter="discount", vwap_mode="rolling"))
            if len(vw):
                if len(sweep):
                    vw = vw[~vw.entry_time.isin(sweep.entry_time)]
                frames.append(vw.assign(grade="B"))
        if frames:
            res["trades"] = pd.concat(frames).sort_values("entry_time").reset_index(drop=True)
        try:
            res["zones"] = e.live_orders(df, p)
        except Exception:
            res["zones"] = pd.DataFrame()
    _CACHE[symbol] = (key, _time.time(), res)
    return res


def _ts(x) -> datetime:
    t = pd.Timestamp(x)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return t.to_pydatetime()


REASON = {"target": "target", "target_gap": "target", "stop": "stop", "stop_gap": "stop",
          "stop_entry_bar": "stop", "time": "expired", "end_of_data": None}


def trade_for_call(db: Session, symbol: str, direction: str, opened: datetime, until: datetime) -> dict:
    """The strategy's first trade on this pair in the call's direction, entered while the call was live.
    Otherwise what it's waiting for (fresh zones on the call's side), or why there's no setup."""
    r = run(db, symbol)
    side = "long" if direction == "LONG" else "short"
    base = {"rules": RULES, "has_volume": r["has_volume"]}
    if not r["enough"]:
        return base | {"state": "no_data", "message": f"Not enough 4-hour candles yet ({len(r['candles'])} of {MIN_CANDLES}): "
                                                      "run FMP price bars on Data health"}
    t = r["trades"]
    if len(t):
        ok = t[(t.side == side) & (t.entry_time.map(_ts) >= opened) & (t.entry_time.map(_ts) <= until)]
        if len(ok):
            x = ok.iloc[0]
            outcome = REASON.get(x.reason)
            return base | {
                "state": "done" if outcome else "open", "grade": x.grade, "entry": float(x.entry),
                "entry_at": _ts(x.entry_time).isoformat(), "stop": float(x.stop), "target": float(x.target),
                "exit": float(x.exit) if outcome else None, "exit_at": _ts(x.exit_time).isoformat() if outcome else None,
                "outcome": outcome, "result_r": round(float(x.R), 2) if outcome else None,
                "zone": {"kind": x.zone_kind, "near": float(x.zone_prox), "far": float(x.zone_dist),
                         "from": _ts(x.zone_base_time).isoformat(), "active": _ts(x.zone_active_time).isoformat()},
                "pattern": x.pattern}
    now = datetime.now(timezone.utc)
    df = r["candles"]
    trend = e.ema(df["Close"], params().trend_ema).iloc[-1]
    with_trend = (df["Close"].iloc[-1] > trend) if side == "long" else (df["Close"].iloc[-1] < trend)
    if until < now:
        return base | {"state": "none", "message": "No setup formed while the call was live"
                                                   + ("" if with_trend else " (the 200 EMA trend was against it)")}
    if not with_trend:
        return base | {"state": "against_trend", "message": "Waiting: price is on the wrong side of the 200 EMA for this "
                                                            f"{'buy' if side == 'long' else 'sell'}, so the rules take no trade yet"}
    z = r["zones"]
    want = "BUY_LIMIT" if side == "long" else "SELL_LIMIT"
    zones = [] if not len(z) else [
        {"near": float(row.limit), "far": float(row.stop), "distance_atr": float(row.distance_atr),
         "created": _ts(row.zone_created).isoformat()} for row in z[z.side == want].head(3).itertuples()]
    return base | {"state": "waiting", "zones": zones,
                   "message": ("Waiting for price to return to a fresh "
                               f"{'demand' if side == 'long' else 'supply'} zone and close back out of it"
                               if zones else f"Waiting for a fresh {'demand' if side == 'long' else 'supply'} zone to form")}


def chart(db: Session, symbol: str, around: datetime | None, end: datetime | None, bars: int = 140) -> list[dict]:
    """4-hour candles for the chart: around a trade, or the latest ones."""
    df = run(db, symbol)["candles"]
    if not len(df):
        return []
    if around is not None:
        i0 = max(0, int(df.index.searchsorted(pd.Timestamp(around))) - 40)
        i1 = int(df.index.searchsorted(pd.Timestamp(end or around))) + 25
        part = df.iloc[i0:min(len(df), max(i1, i0 + 60))]
    else:
        part = df.iloc[-bars:]
    ema_s = e.ema(df["Close"], params().trend_ema).reindex(part.index)
    return [{"t": ts.isoformat(), "o": round(float(r.Open), 6), "h": round(float(r.High), 6),
             "l": round(float(r.Low), 6), "c": round(float(r.Close), 6),
             "ema": None if pd.isna(ema_s.loc[ts]) else round(float(ema_s.loc[ts]), 6)}
            for ts, r in part.iterrows()]
