"""Top setups table (Home page): one row per symbol, one column per factor, each -2..+2, summed into a score.

Columns
  Trend & sentiment:   Trend (price vs its 20/50-day averages), Seasonality, COT, Retail sentiment (contrarian)
  Macro / economic:    CB tone, Rate expectations, GDP, mPMI, sPMI, Retail sales, Consumer confidence, CPI, PPI, PCE,
                       Interest rates (last decision), NFP / employment change, Unemployment rate, Jobless claims, ADP, JOLTS

For a currency pair, each currency gets +1 (hawkish / beat), -1 (dovish / missed) or 0 per column, and the pair cell is
base minus quote (so -2..+2). Gold, silver and the T-note read the US columns the other way round (soft US data is
good for them); the S&P 500 uses the stocks impact (strong growth good, hot inflation bad).
Score = sum of all cells. Bias: 7+ Very Bullish, 4+ Bullish, -3..3 Neutral, -4 or less Bearish, -7 or less Very Bearish.
"""
from __future__ import annotations

import statistics
import time as _time
from datetime import date

from sqlalchemy.orm import Session

from app.analytics import cot as ca
from app.analytics import seasonality as sx
from app.analytics import setups as st
from app.engines import fundamentals as fnd
from app.services import cot, heatmap, retail
from app.services import seasonality as ss
from app.services.daily_moves import daily_moves

FX = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
MAJORS = ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD"]
CROSSES = ["EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD", "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD",
           "GBPNZD", "AUDJPY", "AUDNZD", "AUDCAD", "AUDCHF", "NZDJPY", "NZDCAD", "NZDCHF", "CADJPY", "CADCHF", "CHFJPY"]
EM = ["USDZAR", "USDMXN"]
OTHER = {"XAUUSD": ("Gold", "Metals"), "XAGUSD": ("Silver", "Metals"), "US500": ("S&P 500", "Indices"),
         "US10T": ("US 10Y T-note", "Bonds")}
CATEGORY = {**{p: "FX majors" for p in MAJORS}, **{p: "FX crosses" for p in CROSSES}, **{p: "FX emerging" for p in EM},
            **{k: v[1] for k, v in OTHER.items()}}

TREND_COLS = [("trend", "Trend"), ("seasonality", "Seasonality"), ("cot", "COT"), ("crowd", "Retail sentiment"), ("news", "News tone")]
MACRO_COLS = [("cb_div", "CB diverg."), ("cb", "CB tone"), ("rate_exp", "Rate expect."), ("gdp", "GDP"), ("mpmi", "mPMI"), ("spmi", "sPMI"),
              ("retail_sales", "Retail sales"), ("conf", "Cnsmr conf"), ("cpi", "CPI YoY"), ("ppi", "PPI"),
              ("pce", "PCE YoY"), ("rates", "Interest rates"), ("nfp", "NFP / Jobs"), ("unemp", "Unemploy. rate"),
              ("claims", "Unemploy. claims"), ("adp", "ADP"), ("jolts", "JOLTS")]
COT_CODE = {"EUR": "099741", "JPY": "097741", "GBP": "096742", "AUD": "232741", "CAD": "090741", "CHF": "092741",
            "ZAR": "122741", "USD": "098662", "XAUUSD": "088691", "XAGUSD": "084691", "US500": "13874A",
            "US10T": "043602"}
VS_USD_SERIES = {"EUR": ("EURUSD", False), "GBP": ("GBPUSD", False), "AUD": ("AUDUSD", False),
                 "NZD": ("NZDUSD", False), "JPY": ("USDJPY", True), "CHF": ("USDCHF", True),
                 "CAD": ("USDCAD", True), "ZAR": ("USDZAR", True), "MXN": ("USDMXN", True)}
_CACHE: dict = {}
TTL = 600


def column_of(code: str, category: str) -> str | None:
    c = code.upper()
    if category == "monetary_policy":
        return None
    if "CORE" in c or c.endswith("_MOM") and ("CPI" in c or "PCE" in c):
        return None
    for key, pats in (("adp", ["ADP"]), ("jolts", ["JOLTS"]), ("claims", ["JOBLESS_CLAIMS", "CLAIMANT"]),
                      ("nfp", ["_NFP", "EMPLOYMENT_CHANGE"]), ("unemp", ["UNEMPLOYMENT"]), ("gdp", ["_GDP_"]),
                      ("mpmi", ["MANUF", "IVEY"]), ("spmi", ["SERVICES", "PMI_COMPOSITE"]),
                      ("retail_sales", ["RETAIL_SALES"]), ("conf", ["CONF", "UMICH"]), ("pce", ["PCE"]),
                      ("ppi", ["PPI"]), ("cpi", ["CPI_YOY", "HICP_YOY"])):
        if any(p in c for p in pats):
            return key
    return None


def _ccy_cells(db: Session, ccy: str, snap) -> dict[str, int]:
    """+1 / -1 / 0 per macro column for one currency (hawkish = +1)."""
    cells: dict[str, int] = {}
    for r in heatmap.rows_for(db, ccy):
        if r.get("actual") is None:
            continue
        col = column_of(r["indicator"], r["category"])
        if col and col not in cells:
            cells[col] = 1 if r["currency_impact"] == "Bullish" else -1 if r["currency_impact"] == "Bearish" else 0
    if snap is not None:
        cbs = st.central_bank_score(snap.policy_score, None, None, None)
        if cbs is not None:
            cells["cb"] = 1 if cbs >= 0.5 else -1 if cbs <= -0.5 else 0
        if snap.implied_change_bps is not None or (snap.prob_hike is not None and snap.prob_cut is not None):
            re_ = st.central_bank_score(None, snap.implied_change_bps, snap.prob_hike, snap.prob_cut)
            cells["rate_exp"] = 1 if re_ and re_ >= 0.4 else -1 if re_ and re_ <= -0.4 else 0
        if snap.last_decision:
            cells["rates"] = {"HIKE": 1, "CUT": -1}.get(snap.last_decision.upper(), 0)
    return cells


def _stock_cells(db: Session) -> dict[str, int]:
    cells: dict[str, int] = {}
    for r in heatmap.rows_for(db, "USD"):
        if r.get("actual") is None:
            continue
        col = column_of(r["indicator"], r["category"])
        if col and col not in cells:
            cells[col] = 1 if r["stocks_impact"] == "Bullish" else -1 if r["stocks_impact"] == "Bearish" else 0
    return cells


def _usd_value(series: dict[str, dict], ccy: str) -> dict | None:
    """Daily value of one unit of `ccy` in USD."""
    if ccy == "USD":
        return None
    key, inv = VS_USD_SERIES[ccy]
    s = series.get(key)
    if not s:
        return None
    return {d: (1 / v if inv else v) for d, v in s.items() if v}


def _pair_obs(series: dict[str, dict], asset: str) -> list[tuple[date, float]]:
    if asset in ("XAUUSD", "XAGUSD"):
        return sorted(series.get(asset, {}).items())
    if asset == "US500":
        return sorted(series.get("SPX", {}).items())
    if asset == "US10T":
        return sorted((d, -v) for d, v in series.get("US10Y", {}).items())  # yields down = T-note up
    b, q = asset[:3], asset[3:]
    vb, vq = _usd_value(series, b), _usd_value(series, q)
    if b == "USD" and vq:
        return sorted((d, 1 / v) for d, v in vq.items())
    if q == "USD" and vb:
        return sorted(vb.items())
    if vb and vq:
        return sorted((d, vb[d] / vq[d]) for d in set(vb) & set(vq))
    return []


def trend_cell(obs: list[tuple[date, float]]) -> int | None:
    if len(obs) < 55:
        return None
    vals = [v for _, v in obs]
    s20, s50 = statistics.fmean(vals[-20:]), statistics.fmean(vals[-50:])
    return (1 if vals[-1] > s50 else -1) + (1 if s20 > s50 else -1)


def season_cell(obs: list[tuple[date, float]], today: date, mode: str = "pct") -> int | None:
    if len(obs) < 500:
        return None
    month = sx.month_stats(sx.monthly_moves(obs, mode, today), 10, today)[today.month - 1]
    weeks = sx.week_stats(sx.weekly_moves(obs, mode, today), 10, today)
    w = sx.week_of(today)
    sc = st.seasonality_score(month, [weeks[w - 1], weeks[w % 52]])
    return None if sc is None else (1 if sc >= 0.35 else -1 if sc <= -0.35 else 0)


def cot_cell(db: Session, code: str) -> int | None:
    rows = cot.rows_of(db, code)
    if len(rows) < 12:
        return None
    spec = ca.net(rows, "spec")
    sc = st.cot_score(ca.cot_index(spec, 52), ca.cot_index(spec[:-4], 52), spec[-1] - spec[-2])
    return None if sc is None else (1 if sc >= 0.4 else -1 if sc <= -0.4 else 0)


CB_NAME = {"USD": "Fed", "EUR": "ECB", "GBP": "BoE", "JPY": "BoJ", "CHF": "SNB", "CAD": "BoC", "AUD": "RBA",
           "NZD": "RBNZ", "ZAR": "SARB", "MXN": "Banxico"}


def divergence_cell(gap: float | None) -> int | None:
    """Policy-score gap between two central banks (0-100 scale): 10+ points = 1, 25+ points = 2."""
    if gap is None:
        return None
    a = abs(gap)
    v = 2 if a >= 25 else 1 if a >= 10 else 0
    return v if gap > 0 else -v


def bias_of(score: int) -> str:
    return ("Very Bullish" if score >= 7 else "Bullish" if score >= 4 else "Very Bearish" if score <= -7
            else "Bearish" if score <= -4 else "Neutral")


def compute(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    hit = _CACHE.get(today)
    if hit and _time.time() - hit[0] < TTL:
        return hit[1]
    snaps = fnd.build_all(db)
    ccy_cells = {c: _ccy_cells(db, c, snaps.get(c)) for c in FX + ["ZAR", "MXN"]}
    stock_cells = _stock_cells(db)
    cot_ccy = {c: cot_cell(db, code) for c, code in COT_CODE.items() if len(c) == 3}
    series = {k: dict(ss._obs(db, k)) for k in ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD", "USDJPY", "USDCHF", "USDCAD",
                                                "USDZAR", "USDMXN", "XAUUSD", "XAGUSD", "SPX", "US10Y"]}
    moves = daily_moves(db, 1)
    from app.services import news as nw

    news_ccy = nw.tone_cells(db)
    pscore = {c: (snaps[c].policy_score if snaps.get(c) is not None else None) for c in FX + ["ZAR", "MXN"]}
    others = [v for c, v in pscore.items() if c != "USD" and v is not None]
    world = statistics.fmean(others) if others else None
    rows = []
    for asset in MAJORS + CROSSES + EM + list(OTHER):
        cells: dict[str, int | None] = {}
        notes: dict[str, str] = {}
        if asset in OTHER:
            name = OTHER[asset][0]
            usd = ccy_cells["USD"]
            if asset == "US500":
                cells.update({k: stock_cells.get(k, 0) for k, _ in MACRO_COLS if k not in ("cb", "rate_exp", "rates")})
                for k in ("cb", "rate_exp", "rates"):
                    cells[k] = -usd.get(k, 0)  # a hawkish Fed is a headwind for stocks
            else:
                # gold, silver and T-notes: soft US data and a dovish Fed are supportive
                cells.update({k: -usd.get(k, 0) for k, _ in MACRO_COLS})
            fed = pscore.get("USD")
            gap = None if fed is None or world is None else world - fed  # Fed more dovish than the rest = positive
            cells["cb_div"] = divergence_cell(gap)
            if gap is not None:
                notes["cb_div"] = (f"Fed policy score {fed:.0f} vs other central banks' average {world:.0f}: "
                                   f"{'Fed relatively dovish (supportive)' if gap > 0 else 'Fed relatively hawkish (headwind)' if gap < 0 else 'in line'}")
            cells["cot"] = cot_cell(db, COT_CODE[asset])
            # hawkish US headlines weigh on gold, silver and T-notes; risk-on headlines help stocks
            nu = news_ccy.get("USD")
            if asset == "US500":
                cells["news"] = None if nu is None else news_ccy.get("_risk", 0) - nu
            else:
                cells["news"] = None if nu is None else -nu
            mode = "bp" if asset == "US10T" else "pct"
            chg = moves.get({"XAUUSD": "GOLD", "XAGUSD": "SILVER", "US500": "SPX500"}.get(asset, ""), {})
            day_change = chg.get("change_pct")
            if asset == "US10T" and moves.get("BONDS"):
                day_change = -moves["BONDS"]["change_bps"]  # bp; yields down = T-note up
        else:
            name = f"{asset[:3]}/{asset[3:]}"
            b, q = asset[:3], asset[3:]
            cb_, cq = ccy_cells.get(b, {}), ccy_cells.get(q, {})
            for k, _ in MACRO_COLS:
                cells[k] = cb_.get(k, 0) - cq.get(k, 0)
            pb, pq = pscore.get(b), pscore.get(q)
            gap = None if pb is None or pq is None else pb - pq
            cells["cb_div"] = divergence_cell(gap)
            if gap is not None:
                hawk, dove = (b, q) if gap >= 0 else (q, b)
                notes["cb_div"] = (f"{CB_NAME.get(b, b)} {pb:.0f} vs {CB_NAME.get(q, q)} {pq:.0f} (0 = very dovish, "
                                   f"100 = very hawkish): {CB_NAME.get(hawk, hawk)} more hawkish by {abs(gap):.0f} points")
            xb, xq = cot_ccy.get(b), cot_ccy.get(q)
            cells["cot"] = (xb or 0) - (xq or 0) if (xb is not None or xq is not None) else None
            nb, nq = news_ccy.get(b), news_ccy.get(q)
            cells["news"] = (nb or 0) - (nq or 0) if (nb is not None or nq is not None) else None
            mode = "pct"
            mb = 0.0 if b == "USD" else moves.get(b, {}).get("change_pct")
            mq = 0.0 if q == "USD" else moves.get(q, {}).get("change_pct")
            day_change = None if mb is None or mq is None else round(((1 + mb / 100) / (1 + mq / 100) - 1) * 100, 3)
        obs = _pair_obs(series, asset)
        cells["trend"] = trend_cell(obs)
        cells["seasonality"] = season_cell(obs, today, "bp" if asset == "US10T" else mode)
        rr = retail.latest(db, "XAUUSD" if asset == "XAUUSD" else asset)
        rs = st.retail_score(rr.long_pct if rr else None)
        cells["crowd"] = None if rs is None else (1 if rs >= 0.5 else -1 if rs <= -0.5 else 0)
        cells = {k: (None if v is None else max(-2, min(2, int(v)))) for k, v in cells.items()}
        score = sum(v for v in cells.values() if v is not None)
        tech = cells.get("trend") or 0
        sentcot = (cells.get("cot") or 0) + (cells.get("crowd") or 0) + (cells.get("news") or 0)
        macro_sum = sum((cells.get(k) or 0) for k, _ in MACRO_COLS)
        rows.append({"symbol": asset, "name": name, "category": CATEGORY[asset], "score": score, "bias": bias_of(score),
                     "cells": cells, "technical": tech, "sentiment_cot": sentcot, "macro": macro_sum,
                     "day_change": day_change, "day_change_unit": "bp" if asset == "US10T" else "%",
                     "retail_long_pct": rr.long_pct if rr else None, "notes": notes})
    rows.sort(key=lambda r: (-r["score"], r["symbol"]))
    out = {"as_of": today.isoformat(),
           "groups": [{"key": "trend", "label": "Trend & sentiment", "columns": [{"key": k, "label": l} for k, l in TREND_COLS]},
                      {"key": "macro", "label": "Macro fundamentals / economic data",
                       "columns": [{"key": k, "label": l} for k, l in MACRO_COLS]}],
           "categories": ["FX majors", "FX crosses", "FX emerging", "Metals", "Indices", "Bonds"],
           "rows": rows}
    _CACHE.clear()
    _CACHE[today] = (_time.time(), out)
    return out


def clear_cache() -> None:
    _CACHE.clear()
