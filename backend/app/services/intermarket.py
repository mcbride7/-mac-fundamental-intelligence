"""Intermarket analysis: how currencies, yields, stocks, commodities and volatility move together.

  relationships  each FX pair (and gold) against the markets that usually drive it: rolling correlations of daily
                 changes (20 / 60 / 120 days), whether the usual sign holds, and an "out of line" check: a rolling
                 regression of the pair on its driver over 120 days gives where the pair "should" be; the gap is
                 shown in standard deviations (z). |z| >= 1.5 = out of line.
  confirmation   per pair: are the drivers moving the pair's way over the last 20 days, and is it cheap / rich?
                 -> a -2..+2 Intermarket cell for Top setups
  regime         stocks, bond yields, commodities and the dollar over 20 days -> risk-on / risk-off / reflation /
                 disinflation / stagflation
  leading        2s10s curve, credit spreads, AUD/JPY, VIX
Daily closes from FRED (stored by the Seasonality and Risk sentiment jobs), Twelve Data (gold) and the official
government bond yield feeds.
"""
from __future__ import annotations

import math
import statistics
import time as _time
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BondYield, IndicatorObservation

_CACHE: dict[str, tuple[float, dict]] = {}
TTL = 600
NAMES = {"EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "AUDUSD": "AUD/USD", "NZDUSD": "NZD/USD", "USDJPY": "USD/JPY",
         "USDCHF": "USD/CHF", "USDCAD": "USD/CAD", "USDZAR": "USD/ZAR", "USDMXN": "USD/MXN", "XAUUSD": "Gold",
         "WTI": "Oil (WTI)", "SPX": "S&P 500", "VIX": "VIX", "US10Y": "US 10Y yield", "US2Y": "US 2Y yield",
         "USD": "Dollar index", "AUDJPY": "AUD/JPY", "HY": "High-yield credit spread", "NIKKEI": "Nikkei 225",
         "EUROSTOXX50": "Euro Stoxx 50", "ASHR": "China CSI 300"}
# pair, driver, expected sign, why
RELATIONS: list[tuple[str, str, int, str]] = [
    ("EURUSD", "SPR:DE-US:2Y", 1, "Euro gains when German 2-year yields rise against US ones"),
    ("GBPUSD", "SPR:GB-US:5Y", 1, "Sterling follows the UK–US 5-year yield gap"),
    ("USDJPY", "US10Y", 1, "USD/JPY rises with US 10-year yields"),
    ("USDJPY", "SPR:US-JP:10Y", 1, "USD/JPY follows the US–Japan 10-year yield gap"),
    ("AUDUSD", "SPR:AU-US:2Y", 1, "Aussie follows the Australia–US 2-year yield gap"),
    ("AUDUSD", "SPX", 1, "Aussie is a risk-on currency: it rises with stocks"),
    ("NZDUSD", "SPX", 1, "Kiwi is a risk-on currency: it rises with stocks"),
    ("NZDUSD", "AUDUSD", 1, "Kiwi tracks the Aussie closely"),
    ("USDCAD", "WTI", -1, "Higher oil lifts the loonie, so USD/CAD falls"),
    ("USDCAD", "SPR:US-CA:2Y", 1, "USD/CAD follows the US–Canada 2-year yield gap"),
    ("USDCHF", "SPR:US-CH:2Y", 1, "USD/CHF follows the US–Swiss 2-year yield gap"),
    ("USDCHF", "VIX", -1, "Fear (VIX up) lifts the safe-haven franc, so USD/CHF falls"),
    ("USDZAR", "XAUUSD", -1, "Higher gold supports the rand, so USD/ZAR falls"),
    ("USDZAR", "VIX", 1, "Fear (VIX up) hurts the rand, so USD/ZAR rises"),
    ("USDMXN", "VIX", 1, "Fear (VIX up) hurts the peso, so USD/MXN rises"),
    ("USDMXN", "WTI", -1, "Higher oil supports the peso, so USD/MXN falls"),
    ("XAUUSD", "US10Y", -1, "Gold falls when US yields rise (higher yields compete with gold)"),
    ("XAUUSD", "USD", -1, "Gold falls when the dollar strengthens"),
]
MATRIX = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD", "USDZAR", "USDMXN", "XAUUSD", "WTI",
          "SPX", "US10Y", "VIX"]
LEVEL_SERIES = {"US10Y", "US2Y", "VIX", "HY"}  # yields / spreads / VIX: use point changes, not % changes


def _seas(db: Session, key: str) -> dict[date, float]:
    return {d: v for d, v in db.execute(select(IndicatorObservation.obs_date, IndicatorObservation.value)
                                        .where(IndicatorObservation.series == "SEAS:" + key))}


def _risk(db: Session, key: str) -> dict[date, float]:
    return {d: v for d, v in db.execute(select(IndicatorObservation.obs_date, IndicatorObservation.value)
                                        .where(IndicatorObservation.series == "RISK:" + key))}


def _yield(db: Session, country: str, tenor: str) -> dict[date, float]:
    return {ts.date(): v for ts, v in db.execute(select(BondYield.ts, BondYield.yield_pct)
                                                 .where(BondYield.country == country, BondYield.tenor == tenor))}


class Loader:
    def __init__(self, db: Session):
        self.db, self.memo = db, {}

    def get(self, key: str) -> dict[date, float]:
        if key in self.memo:
            return self.memo[key]
        if key.startswith("SPR:"):  # yield gap a - b in percentage points, e.g. SPR:DE-US:2Y
            _, pair, tenor = key.split(":")
            a, b = pair.split("-")
            ya, yb = self._y(a, tenor), self._y(b, tenor)
            out = {d: round(ya[d] - yb[d], 4) for d in ya.keys() & yb.keys()}
        elif key == "AUDJPY":
            a, j = self.get("AUDUSD"), self.get("USDJPY")
            out = {d: a[d] * j[d] for d in a.keys() & j.keys()}
        elif key == "HY":
            out = _risk(self.db, "hy_oas")
        else:
            out = _seas(self.db, key)
            if key == "US10Y" and not out:
                out = self._y("US", "10Y")
        self.memo[key] = out
        return out

    def _y(self, country: str, tenor: str) -> dict[date, float]:
        if country == "US" and tenor in ("2Y", "10Y"):
            s = _seas(self.db, "US" + tenor)
            if s:
                return s
        return _yield(self.db, country, tenor)


def _aligned(a: dict, b: dict, n: int) -> list[tuple[date, float, float]]:
    ds = sorted(a.keys() & b.keys())[-(n + 1):]
    return [(d, a[d], b[d]) for d in ds]


def _chg(vals: list[float], level: bool) -> list[float]:
    out = []
    for x, y in zip(vals, vals[1:]):
        out.append(y - x if level else (math.log(y / x) if x > 0 and y > 0 else 0.0))
    return out


def _corr(x: list[float], y: list[float]) -> float | None:
    if len(x) < 10:
        return None
    try:
        return round(statistics.correlation(x, y), 2)
    except statistics.StatisticsError:
        return None


def relation(ld: Loader, pair: str, driver: str, sign: int, why: str) -> dict | None:
    p, d = ld.get(pair), ld.get(driver)
    rows = _aligned(p, d, 250)
    if len(rows) < 40:
        return {"pair": pair, "driver": driver, "name": NAMES.get(pair, pair), "driver_name": _dname(driver),
                "expected": sign, "why": why, "status": "No data", "z": None}
    pl = pair in LEVEL_SERIES or pair.startswith("SPR:")
    dl = driver in LEVEL_SERIES or driver.startswith("SPR:")
    pv, dv = [r[1] for r in rows], [r[2] for r in rows]
    pc, dc = _chg(pv, pl), _chg(dv, dl)
    corrs = {w: _corr(pc[-w:], dc[-w:]) for w in (20, 60, 120)}
    # fair value: regress the pair's level on the driver's level over the last 120 days
    win = rows[-120:]
    xs, ys = [r[2] for r in win], [r[1] for r in win]
    fair, z, beta = None, None, None
    if len(win) >= 60 and statistics.pstdev(xs) > 0:
        beta = statistics.covariance(xs, ys) / statistics.variance(xs)
        alpha = statistics.fmean(ys) - beta * statistics.fmean(xs)
        res = [y - (alpha + beta * x) for x, y in zip(xs, ys)]
        sd = statistics.pstdev(res)
        fair = alpha + beta * xs[-1]
        z = round(res[-1] / sd, 2) if sd > 0 else None
        if (beta > 0) != (sign > 0):
            z = None  # the level relationship currently runs the wrong way: no fair value
    c60 = corrs[60]
    if c60 is None:
        status = "No data"
    elif c60 * sign >= 0.2:
        status = "Working"
    elif c60 * sign <= -0.2:
        status = "Flipped"
    else:
        status = "Weak"
    # what the driver says about the pair over 20 days
    d20 = dc[-20:]
    move = (dv[-1] - dv[-21]) if dl else math.log(dv[-1] / dv[-21]) if dv[-21] > 0 else 0
    sd20 = statistics.pstdev(dc[-120:]) * math.sqrt(20) if len(dc) >= 120 else None
    impulse = 0
    if sd20 and abs(move) > 0.5 * sd20 and status == "Working":  # only links that are currently working count
        impulse = 1 if move * sign > 0 else -1
    note = None
    if status != "Working":
        z_used = None
    else:
        z_used = z
    if z_used is not None and abs(z_used) >= 1.5:
        cheap = z < 0
        note = (f"{NAMES.get(pair, pair)} looks {'cheap' if cheap else 'rich'} against {_dname(driver)}: about "
                f"{abs(z):.1f} standard deviations {'below' if cheap else 'above'} where the last 120 days' link puts it")
    return {"pair": pair, "driver": driver, "name": NAMES.get(pair, pair), "driver_name": _dname(driver), "expected": sign,
            "why": why, "corr": corrs, "status": status, "beta": round(beta, 4) if beta is not None else None,
            "fair": _r(fair, pair), "price": _r(pv[-1], pair), "z": z, "z_used": z_used, "note": note, "impulse": impulse,
            "driver_move": round(move * (1 if dl else 100), 2), "driver_unit": "pp" if dl else "%",
            "as_of": rows[-1][0].isoformat(),
            "chart": [{"d": r[0].isoformat(), "p": r[1], "x": r[2]} for r in rows[-180:]]}


def _r(v: float | None, pair: str) -> float | None:
    if v is None:
        return None
    return round(v, 2 if pair in ("USDJPY", "XAUUSD", "SPX", "WTI") or v > 20 else 4)


def _dname(key: str) -> str:
    if key.startswith("SPR:"):
        _, pair, tenor = key.split(":")
        a, b = pair.split("-")
        return f"{a}–{b} {tenor} yield gap"
    return NAMES.get(key, key)


def confirmation(rels: list[dict]) -> dict[str, dict]:
    """Per pair: drivers' 20-day push (+1 / -1 each) plus a catch-up nudge when the pair is out of line."""
    out: dict[str, dict] = {}
    for r in rels:
        if r.get("status") in (None, "No data"):
            continue
        o = out.setdefault(r["pair"], {"push": 0, "n": 0, "z": [], "reasons": []})
        o["push"] += r["impulse"]
        o["n"] += 1
        if r["impulse"]:
            o["reasons"].append(f"{r['driver_name']} {'supports' if r['impulse'] > 0 else 'works against'} a rise")
        if r.get("z_used") is not None:
            o["z"].append(r["z_used"])
    for pair, o in out.items():
        zbar = statistics.fmean(o["z"]) if o["z"] else 0.0
        catch = 1 if zbar <= -1.5 else -1 if zbar >= 1.5 else 0
        if catch:
            o["reasons"].append(f"looks {'cheap' if catch > 0 else 'rich'} vs its drivers (z {zbar:+.1f})")
        o["score"] = max(-2, min(2, o["push"] + catch))
        o["z"] = round(zbar, 2) if o["z"] else None
    return out


def currency_scores(conf: dict[str, dict]) -> dict[str, int]:
    """Intermarket support for each currency against the dollar (USD = 0)."""
    s = {"USD": 0}
    for pair, o in conf.items():
        if pair.endswith("USD") and pair != "XAUUSD":
            s[pair[:3]] = o["score"]
        elif pair.startswith("USD"):
            s[pair[3:]] = -o["score"]
    return s


def regime(ld: Loader) -> dict:
    def ch(key: str, level: bool = False) -> float | None:
        v = ld.get(key)
        ds = sorted(v)[-21:]
        if len(ds) < 21:
            return None
        a, b = v[ds[0]], v[ds[-1]]
        return (b - a) if level else ((b / a - 1) * 100 if a else None)
    stocks, yields, oil, gold, dollar, vix = ch("SPX"), ch("US10Y", True), ch("WTI"), ch("XAUUSD"), ch("USD"), ch("VIX", True)
    moves = {"Stocks (S&P 500)": stocks, "US 10Y yield (pp)": yields, "Oil": oil, "Gold": gold, "Dollar index": dollar,
             "VIX (points)": vix}
    sgn = lambda x, t: 0 if x is None or abs(x) < t else (1 if x > 0 else -1)  # noqa: E731
    s, y, c, u = sgn(stocks, 1.0), sgn(yields, 0.08), sgn(oil, 3.0), sgn(dollar, 0.7)
    patterns = {
        "Risk-on": (1, 0, 0, -1), "Risk-off": (-1, -1, 0, 1), "Reflation": (1, 1, 1, -1),
        "Disinflation (goldilocks)": (1, -1, -1, 0), "Stagflation": (-1, 1, 1, 0), "Deflation scare": (-1, -1, -1, 1)}
    best, score = "Mixed", 0
    for name, pat in patterns.items():
        sc = sum(1 for got, want in zip((s, y, c, u), pat) if want and got == want) - \
            sum(1 for got, want in zip((s, y, c, u), pat) if want and got == -want)
        if sc > score:
            best, score = name, sc
    if score < 2:
        best = "Mixed"
    expl = {"Risk-on": "Stocks up and the dollar down: growth and carry currencies (AUD, NZD, MXN, ZAR) tend to do well, JPY and CHF lag.",
            "Risk-off": "Stocks and yields down, dollar up: safe havens (USD, JPY, CHF, gold) tend to do well.",
            "Reflation": "Stocks, yields and commodities up, dollar down: commodity currencies (AUD, CAD, NZD, NOK) and cyclicals lead.",
            "Disinflation (goldilocks)": "Stocks up as yields and commodities fall: bonds and growth stocks do well; low-yielders steady.",
            "Stagflation": "Stocks down while yields and commodities rise: hard for most assets; oil exporters and gold hold up best.",
            "Deflation scare": "Stocks, yields and commodities all down, dollar up: bonds, USD and JPY lead.",
            "Mixed": "Markets aren't moving in one clear pattern."}[best]
    return {"label": best, "explanation": expl, "moves": {k: (round(v, 2) if v is not None else None) for k, v in moves.items()}}


def leading(ld: Loader) -> list[dict]:
    out = []
    t10, t2 = ld.get("US10Y"), ld.get("US2Y")
    ds = sorted(t10.keys() & t2.keys())
    if len(ds) > 63:
        now = t10[ds[-1]] - t2[ds[-1]]
        before = t10[ds[-64]] - t2[ds[-64]]
        out.append({"name": "US 2s10s curve", "value": f"{now * 100:+.0f} bp",
                    "change": f"{(now - before) * 100:+.0f} bp over 3 months",
                    "read": ("Inverted: markets expect cuts / slower growth" if now < 0 else
                             "Steepening from inversion: historically late-cycle, often before a slowdown"
                             if now - before > 0.25 and before < 0.3 else "Normal upward slope")})
    hy = ld.get("HY")
    ds = sorted(hy)
    if len(ds) > 21:
        ch = hy[ds[-1]] - hy[ds[-21]]
        out.append({"name": "High-yield credit spread", "value": f"{hy[ds[-1]]:.2f}%", "change": f"{ch * 100:+.0f} bp over 1 month",
                    "read": "Widening: stress building, often ahead of weaker stocks" if ch > 0.3 else
                    "Tightening: credit markets relaxed, supportive for risk" if ch < -0.2 else "Stable"})
    aj = ld.get("AUDJPY")
    ds = sorted(aj)
    if len(ds) > 21:
        ch = (aj[ds[-1]] / aj[ds[-21]] - 1) * 100
        out.append({"name": "AUD/JPY (risk gauge)", "value": f"{aj[ds[-1]]:.2f}", "change": f"{ch:+.1f}% over 1 month",
                    "read": "Rising: risk appetite improving" if ch > 1 else "Falling: risk appetite fading" if ch < -1 else "Flat"})
    vx = ld.get("VIX")
    ds = sorted(vx)
    if ds:
        v = vx[ds[-1]]
        out.append({"name": "VIX (fear gauge)", "value": f"{v:.1f}", "change": "",
                    "read": "Calm (below 15)" if v < 15 else "Normal" if v < 20 else "Elevated (20+)" if v < 30 else "Stress (30+)"})
    return out


def matrix(ld: Loader, window: int = 60) -> dict:
    chg = {}
    for k in MATRIX:
        v = ld.get(k)
        ds = sorted(v)
        chg[k] = {d: (v[d] - v[p]) if k in LEVEL_SERIES else (math.log(v[d] / v[p]) if v[p] > 0 and v[d] > 0 else 0.0)
                  for p, d in zip(ds, ds[1:])}
    keys = [k for k in MATRIX if len(chg[k]) > 30]
    cells = []
    for a in keys:
        row = []
        for b in keys:
            if a == b:
                row.append(1.0)
                continue
            ds = sorted(chg[a].keys() & chg[b].keys())[-window:]
            row.append(_corr([chg[a][d] for d in ds], [chg[b][d] for d in ds]))
        cells.append(row)
    return {"keys": keys, "names": [NAMES.get(k, k) for k in keys], "window": window, "cells": cells}


def board(db: Session, window: int = 60) -> dict:
    key = f"b{window}"
    hit = _CACHE.get(key)
    if hit and _time.time() - hit[0] < TTL:
        return hit[1]
    ld = Loader(db)
    rels = [r for r in (relation(ld, *x) for x in RELATIONS) if r]
    conf = confirmation(rels)
    res = {"relationships": rels, "confirmation": conf, "currency_scores": currency_scores(conf),
           "regime": regime(ld), "leading": leading(ld), "matrix": matrix(ld, window),
           "out_of_line": sorted([{k: r[k] for k in ("pair", "name", "driver_name", "z", "note", "price", "fair")}
                                  for r in rels if r.get("note")], key=lambda r: -abs(r["z"]))}
    _CACHE[key] = (_time.time(), res)
    return res


def clear_cache() -> None:
    _CACHE.clear()
