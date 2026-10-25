"""1-day moves for the Daily Evaluation boxes and price tiles.

Currencies are measured against the US dollar (a positive number = that currency got stronger); the US
dollar itself is the average of its moves against the others. Prices come from Twelve Data where
available, otherwise from FRED's daily series (which can be a day or a few days behind).
Bonds are shown as the US 10-year yield change in basis points: yields up = bond prices down.
"""
from __future__ import annotations

import statistics

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BondYield, IndicatorObservation

VS_USD = {"AUD": ("AUDUSD", 1), "NZD": ("NZDUSD", 1), "EUR": ("EURUSD", 1), "GBP": ("GBPUSD", 1),
          "CAD": ("USDCAD", -1), "JPY": ("USDJPY", -1), "CHF": ("USDCHF", -1), "ZAR": ("USDZAR", -1),
          "MXN": ("USDMXN", -1), "CNY": ("USDCNY", -1)}
FRED_FALLBACK = {"USDJPY": "usdjpy", "USDCHF": "usdchf", "AUDUSD": "audusd", "USDZAR": "usdzar",
                 "USDMXN": "usdmxn", "SPX": "spx", "XAUUSD": "gold"}


def _last_two(db: Session, name: str) -> tuple[float, float] | None:
    rows = list(db.scalars(select(IndicatorObservation).where(IndicatorObservation.series == "RISK:" + name)
                           .order_by(IndicatorObservation.obs_date.desc()).limit(2)))
    return (rows[1].value, rows[0].value) if len(rows) == 2 else None


def _pct(pair: tuple[float, float] | None) -> float | None:
    if not pair or not pair[0]:
        return None
    return round((pair[1] / pair[0] - 1) * 100, 3)


def symbol_changes(db: Session) -> dict[str, dict]:
    """symbol -> {price, change_pct, source}, Twelve Data first, FRED daily as fallback."""
    from app.engines.market_engine import markets_overview

    out = {}
    for m in markets_overview(db):
        if m.get("price") is not None and m.get("change_1d_pct") is not None:
            out[m["symbol"]] = {"price": m["price"], "change_pct": m["change_1d_pct"], "source": m.get("source")}
    for sym, name in FRED_FALLBACK.items():
        if sym not in out:
            two = _last_two(db, name)
            if two:
                out[sym] = {"price": two[1], "change_pct": _pct(two), "source": "FRED (daily)"}
    return out


def ten_year(db: Session) -> dict | None:
    two = _last_two(db, "us10y")
    if two is None:
        ys = list(db.scalars(select(BondYield).where(BondYield.country == "US", BondYield.tenor == "10Y")
                            .order_by(BondYield.ts.desc()).limit(2)))
        two = (ys[1].yield_pct, ys[0].yield_pct) if len(ys) == 2 else None
    if two is None:
        return None
    return {"yield": two[1], "change_bps": round((two[1] - two[0]) * 100, 1)}


def daily_moves(db: Session) -> dict[str, dict]:
    sym = symbol_changes(db)
    out: dict[str, dict] = {}
    for ccy, (s, sign) in VS_USD.items():
        if s in sym:
            out[ccy] = {"change_pct": round(sign * sym[s]["change_pct"], 3), "against": "USD"}
    others = [v["change_pct"] for v in out.values()]
    if others:
        out["USD"] = {"change_pct": round(-statistics.fmean(others), 3), "against": "others"}
    for name, s in (("GOLD", "XAUUSD"), ("SPX500", "SPX"), ("BTC", "BTCUSD")):
        if s in sym:
            out[name] = {"change_pct": sym[s]["change_pct"]}
    vix = _last_two(db, "vix")
    if vix:
        out["VIX"] = {"change_pct": _pct(vix), "level": vix[1]}
    ty = ten_year(db)
    if ty:
        out["BONDS"] = {"change_bps": ty["change_bps"], "yield": ty["yield"]}
    return out
