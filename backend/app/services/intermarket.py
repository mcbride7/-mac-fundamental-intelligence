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
         "EUROSTOXX50": "Euro Stoxx 50", "ASHR": "China CSI 300", "CHINA": "China stocks (CSI 300)",
         "REAL10Y": "US 10Y real yield", "COPPER": "Copper", "DAX": "DAX", "NASDAQ": "Nasdaq",
         "DJIA": "Dow Jones", "XAGUSD": "Silver", "BTC": "Bitcoin", "ETH": "Ethereum", "LIQ": "US net liquidity",
         "US5Y": "US 5Y yield", "US30Y": "US 30Y yield"}
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
    ("XAUUSD", "REAL10Y", -1, "Gold falls when US real (inflation-adjusted) yields rise"),
    ("XAUUSD", "US10Y", -1, "Gold falls when US yields rise (higher yields compete with gold)"),
    ("XAUUSD", "USD", -1, "Gold falls when the dollar strengthens"),
    ("USD", "US2Y", 1, "The dollar rises with US 2-year yields (rate expectations)"),
    ("USD", "US10Y", 1, "The dollar rises with US 10-year yields"),
    ("AUDUSD", "COPPER", 1, "Aussie follows copper (Australia's metals exports)"),
    ("AUDUSD", "CHINA", 1, "Aussie follows Chinese stocks (China's growth, Australia's biggest customer)"),
    ("SPX", "US10Y", 0, "Stocks vs bond yields: together when growth drives yields, opposite when inflation / rates do"),
    ("BTC", "NASDAQ", 1, "Bitcoin trades like a risk asset alongside tech stocks"),
    ("BTC", "LIQ", 1, "Bitcoin rises when US liquidity grows (Fed balance sheet minus Treasury cash and reverse repo; weekly)"),
]
MATRIX = ["USD", "EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD", "USDZAR", "XAUUSD", "XAGUSD",
          "WTI", "COPPER", "SPX", "NASDAQ", "DAX", "US2Y", "US10Y", "REAL10Y", "VIX", "BTC"]
LEVEL_SERIES = {"US10Y", "US2Y", "US5Y", "US30Y", "REAL10Y", "VIX", "HY"}
FX_LEGS = {"EUR": ("EURUSD", False), "GBP": ("GBPUSD", False), "AUD": ("AUDUSD", False), "NZD": ("NZDUSD", False),
           "JPY": ("USDJPY", True), "CHF": ("USDCHF", True), "CAD": ("USDCAD", True), "ZAR": ("USDZAR", True),
           "MXN": ("USDMXN", True)}  # yields / spreads / VIX: use point changes, not % changes


def _seas(db: Session, key: str) -> dict[date, float]:
    return {d: v for d, v in db.execute(select(IndicatorObservation.obs_date, IndicatorObservation.value)
                                        .where(IndicatorObservation.series == "SEAS:" + key))}


def _risk(db: Session, key: str) -> dict[date, float]:
    return {d: v for d, v in db.execute(select(IndicatorObservation.obs_date, IndicatorObservation.value)
                                        .where(IndicatorObservation.series == "RISK:" + key))}


def _im(db: Session, key: str) -> dict[date, float]:
    return {d: v for d, v in db.execute(select(IndicatorObservation.obs_date, IndicatorObservation.value)
                                        .where(IndicatorObservation.series == "IM:" + key))}


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
        elif key in ("REAL10Y", "COPPER", "DAX"):
            out = _im(self.db, key)
        elif key == "CHINA":
            out = _seas(self.db, "ASHR")
        elif key == "LIQ":
            out = self._liquidity()
        elif key in ("US5Y", "US30Y"):
            out = self._y("US", key[2:])
        elif len(key) == 6 and key not in {n for n, _ in FX_LEGS.values()} and key[:3] != key[3:] \
                and key[:3] in FX_LEGS | {"USD": None} and key[3:] in FX_LEGS | {"USD": None} and not _seas(self.db, key):
            out = self._cross(key[:3], key[3:])
        else:
            out = _seas(self.db, key)
            if key == "US10Y" and not out:
                out = self._y("US", "10Y")
        self.memo[key] = out
        return out

    def _usd_value(self, ccy: str) -> dict[date, float]:
        """Value of one unit of ccy in US dollars."""
        name, inv = FX_LEGS[ccy]
        s = self.get(name)
        return {d: (1 / v if inv else v) for d, v in s.items() if v}

    def _cross(self, a: str, b: str) -> dict[date, float]:
        if b == "USD":
            return self._usd_value(a)
        vb = self._usd_value(b)
        if a == "USD":
            return {d: 1 / v for d, v in vb.items() if v}
        va = self._usd_value(a)
        return {d: va[d] / vb[d] for d in va.keys() & vb.keys() if vb[d]}

    def _liquidity(self) -> dict[date, float]:
        """Fed balance sheet - Treasury General Account - overnight reverse repo, in $ billions (weekly)."""
        bs, tga, rrp = _im(self.db, "WALCL"), _im(self.db, "TGA"), _im(self.db, "RRP")
        rr = sorted(rrp.items())
        out = {}
        for d in sorted(bs.keys() & tga.keys()):
            prior = [v for dd, v in rr if dd <= d][-1:] if rr else []
            out[d] = round(bs[d] / 1000 - tga[d] / 1000 - (prior[0] if prior else 0.0), 1)
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
    if sign == 0:  # a regime-dependent link: report which way it runs, no fair value or push
        status = ("No data" if c60 is None else "Moving together" if c60 >= 0.2 else "Moving opposite" if c60 <= -0.2
                  else "Weak")
        return {"pair": pair, "driver": driver, "name": NAMES.get(pair, pair), "driver_name": _dname(driver),
                "expected": 0, "why": why, "corr": corrs, "status": status, "z": None, "z_used": None, "note": None,
                "impulse": 0, "beta": None, "fair": None, "price": _r(pv[-1], pair), "driver_move": None,
                "driver_unit": "", "as_of": rows[-1][0].isoformat(),
                "read": ("Stocks and yields rising and falling together: growth is in charge" if status == "Moving together"
                         else "Higher yields are hurting stocks: inflation / rates are in charge" if status == "Moving opposite"
                         else "No clear link right now"),
                "chart": [{"d": r[0].isoformat(), "p": r[1], "x": r[2]} for r in rows[-180:]]}
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


# --------------------------------------------------------------------------- moves in "normal-size" units

def zmove(ld: Loader, key: str, days: int = 20) -> float | None:
    """The last `days` move divided by the typical size of such a move over the last year (so 1.0 = a normal move)."""
    v = ld.get(key)
    ds = sorted(v)
    if len(ds) < days + 60:
        return None
    lvl = key in LEVEL_SERIES or key.startswith("SPR:") or key == "LIQ"
    vals = [v[d] for d in ds[-260:]]
    chg = [(vals[i] - vals[i - days]) if lvl else (math.log(vals[i] / vals[i - days]) if vals[i - days] > 0 and vals[i] > 0 else 0.0)
           for i in range(days, len(vals))]
    sd = statistics.pstdev(chg) if len(chg) > 5 else 0
    return round(chg[-1] / sd, 2) if sd > 0 else None


def risk_environment(ld: Loader) -> dict:
    """Risk-on / risk-off / neutral from equities, volatility, bonds, currencies, commodities and credit (20 days)."""
    parts = [("Stocks (S&P 500)", "SPX", 1), ("Volatility (VIX)", "VIX", -1), ("Credit spreads", "HY", -1),
             ("Bond yields (US 10Y)", "US10Y", 1), ("AUD/JPY", "AUDJPY", 1), ("Copper", "COPPER", 1),
             ("Gold vs stocks", None, -1)]
    comps, vals = [], []
    for name, key, sign in parts:
        if key is None:
            g, sp = zmove(ld, "XAUUSD"), zmove(ld, "SPX")
            z = None if g is None or sp is None else round(g - sp, 2)
        else:
            z = zmove(ld, key)
        if z is None:
            continue
        contrib = max(-2.0, min(2.0, z * sign))
        vals.append(contrib)
        comps.append({"name": name, "z": z, "contribution": round(contrib, 2),
                      "reads": "risk-on" if contrib > 0.3 else "risk-off" if contrib < -0.3 else "neutral"})
    if not vals:
        return {"label": "No data", "score": None, "components": []}
    score = round(50 * statistics.fmean(vals))  # -100..100
    label = "Risk-on" if score >= 20 else "Risk-off" if score <= -20 else "Neutral"
    agree = sum(1 for c in comps if (c["contribution"] > 0.3) == (score > 0) and abs(c["contribution"]) > 0.3)
    return {"label": label, "score": score, "components": comps,
            "agreement": f"{agree} of {len(comps)} markets agree"}


# --------------------------------------------------------------------------- divergences

DIVERGENCES = [
    # a, b, expected relation (+1 same way / -1 opposite), title, possible explanations
    ("US10Y", "USD", 1, "US yields and the dollar disagree",
     ["Foreign yields may be rising faster than US ones (check the yield gaps under Bonds & rates)",
      "Long yields may be rising on fiscal or inflation worries (term premium) rather than growth, which doesn't help the dollar",
      "Risk-on flows can pull money out of the safe-haven dollar even as yields rise",
      "Reserve managers diversifying away from the dollar"]),
    ("REAL10Y", "XAUUSD", -1, "Gold is ignoring US real yields",
     ["Central bank gold buying", "Geopolitical or financial-stability hedging",
      "Inflation or currency-debasement fears", "Momentum / speculative positioning (check COT)"]),
    ("USD", "XAUUSD", -1, "Gold and the dollar are moving the same way",
     ["Safe-haven demand lifting both", "Central bank gold buying", "Geopolitical stress"]),
    ("SPX", "VIX", -1, "Stocks and volatility are rising together",
     ["Investors buying protection ahead of an event (data, central bank, election)", "A narrow, fragile rally",
      "Option-market positioning (VIX demand) rather than real fear"]),
    ("SPX", "HY", -1, "Stocks and credit disagree",
     ["Credit often turns first: widening spreads can warn of stock weakness ahead",
      "Stress in lower-quality borrowers that large-cap indices don't show yet"]),
    ("WTI", "USDCAD", -1, "Oil and the Canadian dollar have decoupled",
     ["The Bank of Canada / rate expectations are driving CAD instead of oil",
      "US data or tariffs dominating USD/CAD", "Oil moving on supply news that doesn't help Canada's terms of trade"]),
    ("COPPER", "AUDUSD", 1, "Copper and the Aussie disagree",
     ["RBA expectations or Australian data dominating", "Worries about China's demand beyond copper (iron ore, steel)",
      "A broad US dollar move overwhelming commodity support"]),
    ("SPR:US-JP:10Y", "USDJPY", 1, "USD/JPY isn't following the US–Japan yield gap",
     ["Safe-haven buying of the yen", "Intervention risk from Japan's Ministry of Finance",
      "Expectations of Bank of Japan hikes not yet in bond yields", "Carry trades being unwound"]),
    ("NASDAQ", "BTC", 1, "Bitcoin has decoupled from tech stocks",
     ["Crypto-specific news (flows, regulation, ETF demand)", "Liquidity changes hitting crypto first"]),
    ("SPX", "US10Y", 0, "Bonds and stocks are telling different stories",
     ["Falling yields while stocks rise can mean bonds are pricing a slowdown that stocks ignore",
      "Rising yields while stocks fall means inflation / rate fears are in charge"]),
]


def divergences(ld: Loader) -> list[dict]:
    out = []
    for a, b, rel, title, why in DIVERGENCES:
        za, zb = zmove(ld, a), zmove(ld, b)
        if za is None or zb is None or abs(za) < 0.75 or abs(zb) < 0.75:
            continue
        if rel == 0:
            if not ((a == "SPX" and za > 0 and zb < -1.0) or (a == "SPX" and za < -0.75 and zb > 1.0)):
                continue
            expl = why[:1] if za > 0 else why[1:]
        else:
            if (za > 0) == ((zb > 0) if rel > 0 else (zb < 0)):
                continue  # they agree: no divergence
            expl = why
        sev = min(abs(za), abs(zb))
        out.append({"title": title, "a": _dname(a), "b": _dname(b), "a_move": za, "b_move": zb,
                    "severity": "Strong" if sev >= 1.5 else "Moderate" if sev >= 1.0 else "Mild",
                    "detail": f"{_dname(a)} {'up' if za > 0 else 'down'} ({za:+.1f}σ) while {_dname(b)} {'up' if zb > 0 else 'down'} "
                              f"({zb:+.1f}σ) over 20 days; they usually move {'together' if rel > 0 else 'opposite ways' if rel < 0 else 'consistently'}.",
                    "explanations": expl})
    rank = {"Strong": 0, "Moderate": 1, "Mild": 2}
    out.sort(key=lambda x: (rank[x["severity"]], -(abs(x["a_move"]) + abs(x["b_move"]))))
    return out


# --------------------------------------------------------------------------- directional bias per asset

SETUP_SERIES = {"US500": "SPX", "XAUUSD": "XAUUSD", "XAGUSD": "XAGUSD"}
WEIGHTS = {"Intermarket": 0.25, "Fundamentals": 0.25, "Rate expectations": 0.20, "Positioning": 0.15, "Price action": 0.15}


def _catalysts(db: Session, ccys: list[str]) -> list[str]:
    from datetime import datetime, timezone

    from app.models import CentralBank, CentralBankMeeting, EconomicEvent, Indicator

    now = datetime.now(timezone.utc)
    rows = db.execute(select(EconomicEvent, Indicator).join(Indicator, EconomicEvent.indicator_id == Indicator.id)
                      .where(Indicator.currency.in_(ccys), Indicator.importance == "high",
                             EconomicEvent.scheduled_at >= now, EconomicEvent.scheduled_at <= now + timedelta(days=8))
                      .order_by(EconomicEvent.scheduled_at).limit(5))
    out = [f"{ev.scheduled_at.strftime('%a %d %b')}: {ind.name}" for ev, ind in rows]
    for m, cb in db.execute(select(CentralBankMeeting, CentralBank).join(CentralBank, CentralBankMeeting.central_bank_id == CentralBank.id)
                            .where(CentralBank.currency.in_(ccys), CentralBankMeeting.meeting_date >= now.date(),
                                   CentralBankMeeting.meeting_date <= now.date() + timedelta(days=21))):
        out.append(f"{m.meeting_date.strftime('%a %d %b')}: {cb.short_name} rate decision")
    return out[:6]


def bias(db: Session, ld: Loader, conf: dict[str, dict], rels: list[dict]) -> list[dict]:
    from app.services import setups_table as tb

    rows = tb.compute(db)["rows"]
    macro_keys = [k for k, _ in tb.MACRO_COLS if k not in ("cb_div", "cb", "rate_exp", "rates")]
    labels = dict(tb.MACRO_COLS)
    out = []
    for r in rows:
        sym, c = r["symbol"], r["cells"]
        if sym == "US10T":
            continue
        comp: dict[str, float | None] = {
            "Intermarket": None if c.get("intermarket") is None else c["intermarket"] / 2,
            "Fundamentals": max(-1.0, min(1.0, sum((c.get(k) or 0) for k in macro_keys) / 5)),
            "Rate expectations": max(-1.0, min(1.0, ((c.get("rate_exp") or 0) + (c.get("cb_div") or 0) + (c.get("cb") or 0)) / 4)),
            "Positioning": None if c.get("cot") is None and c.get("crowd") is None else
            max(-1.0, min(1.0, ((c.get("cot") or 0) + (c.get("crowd") or 0)) / 3)),
            "Price action": None if c.get("trend") is None else c["trend"] / 2,
        }
        have = {k: v for k, v in comp.items() if v is not None}
        if not have:
            continue
        w = sum(WEIGHTS[k] for k in have)
        score = round(100 * sum(WEIGHTS[k] * v for k, v in have.items()) / w)
        direction = "Bullish" if score >= 20 else "Bearish" if score <= -20 else "Neutral"
        sgn = 1 if score > 0 else -1 if score < 0 else 0
        support = [f"{k} ({'+' if v > 0 else ''}{round(v * 100)})" for k, v in have.items() if sgn and v * sgn > 0.15]
        conflict = [f"{k} ({'+' if v > 0 else ''}{round(v * 100)})" for k, v in have.items() if sgn and v * sgn < -0.15]
        im_note = r.get("notes", {}).get("intermarket")
        if im_note:
            (support if (c.get("intermarket") or 0) * sgn > 0 else conflict if (c.get("intermarket") or 0) * sgn < 0 else []).append(im_note)
        pos = [f"{labels[k]} {'+' if c[k] > 0 else ''}{c[k]}" for k in macro_keys if (c.get(k) or 0) > 0]
        neg = [f"{labels[k]} {c[k]}" for k in macro_keys if (c.get(k) or 0) < 0]
        fund = []
        if c.get("cb_div"):
            fund.append(r.get("notes", {}).get("cb_div") or f"Central bank divergence {c['cb_div']:+d}")
        if pos:
            fund.append("Data in favour: " + ", ".join(pos[:5]))
        if neg:
            fund.append("Data against: " + ", ".join(neg[:5]))
        ccys = [sym[:3], sym[3:]] if len(sym) == 6 and sym not in ("XAUUSD", "XAGUSD") else ["USD"]
        key = SETUP_SERIES.get(sym, sym)
        series = ld.get(key)
        ds = sorted(series)[-21:]
        inval = []
        if len(ds) >= 21 and direction != "Neutral":
            lo, hi = min(series[d] for d in ds), max(series[d] for d in ds)
            lvl = _r(lo if direction == "Bullish" else hi, key)
            inval.append(f"A daily close {'below the 20-day low' if direction == 'Bullish' else 'above the 20-day high'} ({lvl})")
        top = [x for x in rels if x["pair"] in (sym, key) and x.get("status") == "Working" and x.get("impulse")]
        for x in top[:2]:
            inval.append(f"{x['driver_name']} reversing its last 20-day move ({x['driver_move']:+}{x['driver_unit']})")
        if direction != "Neutral" and not inval:
            inval.append("The fundamentals or rate expectations flipping (watch the next data releases)")
        out.append({"symbol": sym, "name": r["name"], "category": r["category"], "direction": direction, "score": score,
                    "strength": abs(score), "components": {k: (None if v is None else round(v * 100)) for k, v in comp.items()},
                    "supporting": support, "conflicting": conflict, "fundamentals": fund,
                    "catalysts": _catalysts(db, ccys), "invalidation": inval})
    out.sort(key=lambda x: -x["strength"])
    return out


# --------------------------------------------------------------------------- bonds, rates, positioning

def bonds_rates(db: Session, ld: Loader) -> dict:
    from app.engines import fundamentals as fnd

    def last_and_change(series: dict, days: int = 21):
        ds = sorted(series)
        if not ds:
            return None, None
        prev = series[ds[-days]] if len(ds) > days else None
        return series[ds[-1]], (None if prev is None else round((series[ds[-1]] - prev) * 100))
    us = []
    for t in ("2Y", "5Y", "10Y", "30Y"):
        v, ch = last_and_change(ld.get("US" + t))
        us.append({"tenor": t, "yield": None if v is None else round(v, 2), "change_1m_bp": ch})
    real, rch = last_and_change(ld.get("REAL10Y"))
    curves = []
    for name, a, b in (("2s10s", "US2Y", "US10Y"), ("5s30s", "US5Y", "US30Y")):
        sa, sb = ld.get(a), ld.get(b)
        ds = sorted(sa.keys() & sb.keys())
        if ds:
            now = (sb[ds[-1]] - sa[ds[-1]]) * 100
            prev = (sb[ds[-22]] - sa[ds[-22]]) * 100 if len(ds) > 22 else None
            curves.append({"name": name, "bp": round(now), "change_1m_bp": None if prev is None else round(now - prev),
                           "shape": "Inverted" if now < 0 else "Flat" if now < 25 else "Normal"})
    gaps = []
    for ccy, cty, tenor in (("EUR", "DE", "2Y"), ("GBP", "GB", "5Y"), ("JPY", "JP", "2Y"), ("CHF", "CH", "2Y"),
                            ("CAD", "CA", "2Y"), ("AUD", "AU", "2Y")):
        g = ld.get(f"SPR:{cty}-US:{tenor}")
        v, ch = last_and_change(g)
        y = ld._y(cty, tenor)
        yv = y[sorted(y)[-1]] if y else None
        gaps.append({"currency": ccy, "tenor": tenor, "yield": None if yv is None else round(yv, 2),
                     "gap_vs_us_bp": None if v is None else round(v * 100), "change_1m_bp": ch,
                     "read": None if ch is None else (f"Moving in {ccy}'s favour" if ch > 5 else f"Moving against {ccy}" if ch < -5 else "Little change")})
    rates = []
    for ccy in ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN"):
        try:
            sn = fnd.build(db, ccy)
        except Exception:
            continue
        if sn.cb is None:
            continue
        rates.append({"currency": ccy, "bank": sn.cb.short_name, "rate": sn.policy_rate,
                      "priced_12m_bp": sn.implied_change_bps, "proxy": sn.implied_is_proxy,
                      "read": None if sn.implied_change_bps is None else
                      ("hikes priced" if sn.implied_change_bps >= 15 else "cuts priced" if sn.implied_change_bps <= -15 else "little priced")})
    return {"us": us, "real_10y": None if real is None else {"yield": round(real, 2), "change_1m_bp": rch},
            "curves": curves, "gaps": gaps, "rates": rates}


def positioning(db: Session) -> list[dict]:
    from app.services import cot

    keep = {"Currencies", "Metals", "Energy", "Equity indices", "Rates"}
    out = []
    for s in cot.board(db):
        if s.get("group") not in keep or not s.get("report_date"):
            continue
        idx = s.get("cot_index_52")
        out.append({"name": s["name"], "group": s["group"], "spec_net": s.get("spec_net"), "change": s.get("spec_change"),
                    "cot_index": idx, "date": s.get("report_date"),
                    "read": None if idx is None else ("Crowded long" if idx >= 90 else "Crowded short" if idx <= 10 else
                                                      "Leaning long" if idx >= 65 else "Leaning short" if idx <= 35 else "Neutral")})
    return out


def desk_note(res: dict) -> str:
    """Plain-English summary of the dashboard (rule-based; the AI version builds on it)."""
    r = res["risk"]
    parts = [f"Global risk: {r['label']}" + (f" (score {r['score']:+d}, {r.get('agreement', '')})." if r.get("score") is not None else ".")]
    if res["regime"]["label"] != "Mixed":
        parts.append(f"Cross-asset pattern: {res['regime']['label'].lower()}.")
    if res["divergences"]:
        d = res["divergences"][0]
        parts.append(f"Main divergence: {d['title'].lower()} ({d['detail']})")
    top = [b for b in res["bias"] if b["direction"] != "Neutral"][:3]
    if top:
        parts.append("Strongest biases: " + "; ".join(f"{b['name']} {b['direction'].lower()} ({b['strength']})" for b in top) + ".")
    return " ".join(parts)


def board(db: Session, window: int = 60) -> dict:
    key = f"b{window}"
    hit = _CACHE.get(key)
    if hit and _time.time() - hit[0] < TTL:
        return hit[1]
    ld = Loader(db)
    rels = [r for r in (relation(ld, *x) for x in RELATIONS) if r]
    conf = confirmation(rels)
    res = {"relationships": rels, "confirmation": conf, "currency_scores": currency_scores(conf),
           "regime": regime(ld), "risk": risk_environment(ld), "leading": leading(ld), "matrix": matrix(ld, window),
           "divergences": divergences(ld),
           "out_of_line": sorted([{k: r[k] for k in ("pair", "name", "driver_name", "z", "note", "price", "fair")}
                                  for r in rels if r.get("note")], key=lambda r: -abs(r["z"]))}
    _CACHE[key] = (_time.time(), res)  # cached before the bias step, which reads Top setups (which reads us)
    try:
        res["bias"] = bias(db, ld, conf, rels)
    except Exception:  # never let one section break the page
        import logging
        logging.getLogger(__name__).exception("intermarket bias failed")
        res["bias"] = []
    try:
        res["bonds"] = bonds_rates(db, ld)
    except Exception:
        res["bonds"] = None
    try:
        res["positioning"] = positioning(db)
    except Exception:
        res["positioning"] = []
    res["note"] = desk_note(res)
    return res


def ai_note(db: Session) -> dict:
    """AI desk note on top of the dashboard numbers (needs an AI key; falls back to the plain summary)."""
    from app.ai.llm import DATA_GUARD, get_llm, wrap_document
    import json as _json

    res = board(db)
    llm = get_llm()
    if not getattr(llm, "available", False):
        return {"text": res["note"], "ai": False}
    facts = {"risk": res["risk"], "regime": res["regime"]["label"], "divergences": res["divergences"][:4],
             "top_biases": [{k: b[k] for k in ("name", "direction", "strength", "supporting", "conflicting", "fundamentals",
                                                "catalysts", "invalidation")} for b in res["bias"][:6]],
             "out_of_line": res["out_of_line"][:4], "leading": res["leading"]}
    prompt = ("You are a macro strategist. Using ONLY the data below, write a short intermarket desk note (max 180 words): "
              "1) the global risk environment and what is driving it, 2) the most important divergence and its likely "
              "explanation, 3) the two or three highest-conviction trade ideas with why, the main risk and what would "
              "invalidate each. Plain English, no hype, say it is not financial advice.\n"
              + wrap_document(_json.dumps(facts, default=str)[:12000]))
    try:
        resp = llm.complete(DATA_GUARD, prompt, 500)
        return {"text": resp.text.strip(), "ai": True, "model": resp.model}
    except Exception:
        return {"text": res["note"], "ai": False}


def clear_cache() -> None:
    _CACHE.clear()
