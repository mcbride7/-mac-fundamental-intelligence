"""Seasonality tracker: long price histories for every asset class and how each behaves by calendar month.

Histories come from FRED (free daily series back to 2000; monthly IMF prices for copper and grains) and from
Twelve Data for gold and silver (about 20 years of daily closes in one request each). They are stored in
indicator_observations under "SEAS:<key>" and refreshed weekly (a few new days each time).
"""
from __future__ import annotations

import logging
import time as _time
from datetime import date

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.analytics import seasonality as sx
from app.config import settings
from app.ingestion.base import SourceUnavailable
from app.models import IndicatorObservation, Source

log = logging.getLogger(__name__)
PREFIX = "SEAS:"
START = "2000-01-01"

# key: (name, group, source, series, mode, note)   mode "pct" = % moves, "bp" = basis-point moves (yields)
ASSETS: dict[str, tuple[str, str, str, str, str, str]] = {
    "EURUSD": ("EUR/USD", "Currencies", "fred", "DEXUSEU", "pct", ""),
    "GBPUSD": ("GBP/USD", "Currencies", "fred", "DEXUSUK", "pct", ""),
    "AUDUSD": ("AUD/USD", "Currencies", "fred", "DEXUSAL", "pct", ""),
    "NZDUSD": ("NZD/USD", "Currencies", "fred", "DEXUSNZ", "pct", ""),
    "USDJPY": ("USD/JPY", "Currencies", "fred", "DEXJPUS", "pct", ""),
    "USDCHF": ("USD/CHF", "Currencies", "fred", "DEXSZUS", "pct", ""),
    "USDCAD": ("USD/CAD", "Currencies", "fred", "DEXCAUS", "pct", ""),
    "USDZAR": ("USD/ZAR", "Currencies", "fred", "DEXSFUS", "pct", ""),
    "USDMXN": ("USD/MXN", "Currencies", "fred", "DEXMXUS", "pct", ""),
    "USDCNY": ("USD/CNY", "Currencies", "fred", "DEXCHUS", "pct", ""),
    "USD": ("US dollar (broad index)", "Currencies", "fred", "DTWEXBGS", "pct", "Fed broad dollar index, from 2006"),
    "XAUUSD": ("Gold", "Metals", "twelvedata", "XAU/USD", "pct", ""),
    "XAGUSD": ("Silver", "Metals", "twelvedata", "XAG/USD", "pct", ""),
    "COPPER": ("Copper", "Metals", "fred", "PCOPPUSDM", "pct", "monthly prices (IMF)"),
    "WTI": ("WTI crude oil", "Energy", "fred", "DCOILWTICO", "pct", ""),
    "BRENT": ("Brent crude oil", "Energy", "fred", "DCOILBRENTEU", "pct", ""),
    "NATGAS": ("Natural gas (Henry Hub)", "Energy", "fred", "DHHNGSP", "pct", ""),
    "SPX": ("S&P 500", "Equities", "fred", "SP500", "pct", "FRED keeps about 10 years"),
    "NASDAQ": ("Nasdaq Composite", "Equities", "fred", "NASDAQCOM", "pct", ""),
    "DJIA": ("Dow Jones", "Equities", "fred", "DJIA", "pct", "FRED keeps about 10 years"),
    "US10Y": ("US 10-year yield", "Rates", "fred", "DGS10", "bp", "moves in basis points"),
    "US2Y": ("US 2-year yield", "Rates", "fred", "DGS2", "bp", "moves in basis points"),
    "BTC": ("Bitcoin", "Crypto", "fred", "CBBTCUSD", "pct", "from 2014"),
    "ETH": ("Ethereum", "Crypto", "fred", "CBETHUSD", "pct", "from 2016"),
    "VIX": ("VIX", "Volatility", "fred", "VIXCLS", "pct", ""),
    "CORN": ("Corn", "Agriculture", "fred", "PMAIZMTUSDM", "pct", "monthly prices (IMF)"),
    "WHEAT": ("Wheat", "Agriculture", "fred", "PWHEAMTUSDM", "pct", "monthly prices (IMF)"),
    "SOYBEANS": ("Soybeans", "Agriculture", "fred", "PSOYBUSDM", "pct", "monthly prices (IMF)"),
}
GROUPS = ["Currencies", "Metals", "Energy", "Equities", "Rates", "Crypto", "Volatility", "Agriculture"]
LOOKBACKS = (5, 10, 15, 20)


# ---------------------------------------------------------------- collecting

def _twelvedata_daily(symbol: str) -> list[tuple[date, float]]:
    import requests

    r = requests.get("https://api.twelvedata.com/time_series",
                     params={"symbol": symbol, "interval": "1day", "outputsize": 5000,
                             "apikey": settings.twelvedata_api_key, "timezone": "UTC"}, timeout=60)
    data = r.json()
    if r.status_code >= 400 or data.get("status") == "error":
        raise SourceUnavailable(f"Twelve Data {symbol}: {data.get('message', r.status_code)}")
    return [(date.fromisoformat(v["datetime"][:10]), float(v["close"])) for v in data.get("values", [])]


def _store(db: Session, key: str, obs: list[tuple[date, float]]) -> int:
    series = PREFIX + key
    have = {d for (d,) in db.execute(select(IndicatorObservation.obs_date).where(IndicatorObservation.series == series))}
    new = [{"series": series, "obs_date": d, "value": v} for d, v in obs if d not in have]
    for i in range(0, len(new), 2000):
        db.execute(insert(IndicatorObservation), new[i:i + 2000])
    db.commit()
    return len(new)


def collect(db: Session) -> tuple[int, list[str]]:
    from app.ingestion.fred import fetch_observations

    n, failed = 0, []
    for key, (_, _, src, series, _, _) in ASSETS.items():
        latest = db.scalar(select(IndicatorObservation.obs_date).where(IndicatorObservation.series == PREFIX + key)
                           .order_by(IndicatorObservation.obs_date.desc()))
        try:
            if src == "fred":
                start = (latest.replace(day=1).isoformat() if latest else START)
                obs = fetch_observations(series, start)
            else:
                if not settings.twelvedata_api_key:
                    failed.append(f"{key}: no TWELVEDATA_API_KEY")
                    continue
                obs = _twelvedata_daily(series)
                _time.sleep(8)  # free plan: about 8 requests a minute
            n += _store(db, key, obs)
        except Exception as exc:  # one asset failing must not stop the rest
            failed.append(f"{key}: {exc}")
    _CACHE.clear()
    return n, failed


def run_seasonality(db: Session, src: Source) -> int:
    n, failed = collect(db)
    if failed:
        log.info("Seasonality: some assets failed: %s", "; ".join(failed))
    if len(failed) == len(ASSETS):
        raise SourceUnavailable("No price history came back. Check FRED_API_KEY. First error: " + failed[0])
    return n


# ---------------------------------------------------------------- views

_CACHE: dict[tuple, dict] = {}


def _obs(db: Session, key: str) -> list[tuple[date, float]]:
    return [(d, v) for d, v in db.execute(select(IndicatorObservation.obs_date, IndicatorObservation.value)
                                          .where(IndicatorObservation.series == PREFIX + key)
                                          .order_by(IndicatorObservation.obs_date))]


def _latest_marker(db: Session) -> str:
    d = db.scalar(select(IndicatorObservation.obs_date).where(IndicatorObservation.series.like(PREFIX + "%"))
                  .order_by(IndicatorObservation.obs_date.desc()))
    return d.isoformat() if d else ""


def asset_view(db: Session, key: str, years: int = 10, today: date | None = None) -> dict:
    if key not in ASSETS:
        raise LookupError(f"Unknown asset {key}")
    today = today or date.today()
    name, group, src, series, mode, note = ASSETS[key]
    obs = _obs(db, key)
    base = {"key": key, "name": name, "group": group, "mode": mode, "note": note,
            "source": "Twelve Data" if src == "twelvedata" else f"FRED ({series})",
            "first": obs[0][0].isoformat() if obs else None, "last": obs[-1][0].isoformat() if obs else None}
    if not obs:
        return base | {"months": [], "grid": [], "path": None, "next_30": None, "this_month": None, "next_month": None}
    moves = sx.monthly_moves(obs, mode, today)
    stats = sx.month_stats(moves, years, today)
    for st in stats:
        st["bias"] = sx.bias(st)
    nm = today.month % 12 + 1
    daily = len(obs) > 400 and (obs[-1][0] - obs[-200][0]).days < 400
    ytd_base = next((v for d, v in reversed(obs) if d.year < today.year), None)
    ytd = sx._move(ytd_base, obs[-1][1], mode) if ytd_base else None
    mtd_base = next((v for d, v in reversed(obs) if (d.year, d.month) < (today.year, today.month)), None)
    mtd = sx._move(mtd_base, obs[-1][1], mode) if mtd_base else None
    weeks, this_week, next_week = [], None, None
    if daily:
        weeks = sx.week_stats(sx.weekly_moves(obs, mode, today), years, today)
        for st in weeks:
            st["bias"] = sx.bias(st)
        w = sx.week_of(today)
        this_week, next_week = weeks[w - 1], weeks[w % 52]
    path = sx.seasonal_path(obs, years, mode, today) if daily else None
    return base | {
        "years": years, "months": stats, "grid": sx.year_grid(moves, years, today),
        "path": path, "price_chart": price_chart(path, obs, mode) if path else None,
        "next_30": sx.forward_window(obs, years, 30, mode, today) if daily else None,
        "this_month": stats[today.month - 1], "next_month": stats[nm - 1],
        "weeks": weeks, "this_week": this_week, "next_week": next_week, "week_now": sx.week_of(today),
        "latest": obs[-1][1], "latest_date": obs[-1][0].isoformat(), "month_to_date": mtd, "year_to_date": ytd,
        # this year's actual move in each month (current month = so far), to set against the averages
        "this_year": [mtd if m == today.month else moves.get((today.year, m)) if m < today.month else None
                      for m in range(1, 13)],
    }


def price_chart(path: dict, obs: list, mode: str) -> dict | None:
    """Actual price this year against the price the seasonal pattern implies, plus where the pattern points
    from today's price to the end of the year."""
    base, avg, cur = path.get("base"), path["average"], path["current"]
    if base is None or not avg:
        return None
    seasonal = [sx.to_price(base, v, mode) for v in avg]
    actual = [sx.to_price(base, v, mode) for v in cur]
    at = path["today_index"]
    now = obs[-1][1]
    proj: list[float | None] = [None] * len(avg)
    if 0 <= at < len(avg) and avg[at] is not None:
        for i in range(at, len(avg)):
            if avg[i] is None:
                continue
            if mode == "bp":
                proj[i] = round(now + (avg[i] - avg[at]) / 100, 4)
            else:
                proj[i] = round(now * (1 + avg[i] / 100) / (1 + avg[at] / 100), 6)
    gap = path.get("gap_vs_average")
    ahead = None
    if proj[-1] is not None:
        ahead = round((proj[-1] - now) * 100, 1) if mode == "bp" else round((proj[-1] / now - 1) * 100, 2)
    unit = " bp" if mode == "bp" else "%"
    if gap is None:
        note = ""
    else:
        side = "above" if gap > 0 else "below" if gap < 0 else "in line with"
        size = "" if gap == 0 else f"{abs(gap):.{0 if mode == 'bp' else 1}f}{unit} "
        note = f"Price is {size}{side} its seasonal path for this time of year."
        if ahead is not None:
            way = "up" if ahead > 0 else "down" if ahead < 0 else "flat"
            note += f" The seasonal pattern points {way} {abs(ahead):.{0 if mode == 'bp' else 1}f}{unit} from here to the end of the year."
    return {"dates": path["dates"], "seasonal": seasonal, "actual": actual, "projection": proj, "today_index": at,
            "latest": now, "gap": gap, "ahead_to_year_end": ahead, "note": note}


def overview(db: Session, years: int = 10, today: date | None = None, view: str = "monthly") -> dict:
    """Every asset by month (or the next 4 weeks), plus the strongest and weakest seasonal tendencies for
    this month and next (or this week and next)."""
    today = today or date.today()
    if view == "weekly":
        return weekly_overview(db, years, today)
    ck = (years, today.isoformat(), _latest_marker(db))
    if ck in _CACHE:
        return _CACHE[ck]
    rows = []
    for key, (name, group, _, _, mode, note) in ASSETS.items():
        obs = _obs(db, key)
        if not obs:
            rows.append({"key": key, "name": name, "group": group, "mode": mode, "note": note, "months": [], "years_of_data": 0})
            continue
        stats = sx.month_stats(sx.monthly_moves(obs, mode, today), years, today)
        for s in stats:
            s["bias"] = sx.bias(s)
        rows.append({"key": key, "name": name, "group": group, "mode": mode, "note": note, "months": stats,
                     "years_of_data": round((obs[-1][0] - obs[0][0]).days / 365.25, 1)})

    def leaders(m: int) -> dict:
        cands = [(r, r["months"][m - 1]) for r in rows if r["months"] and r["months"][m - 1]["n"] >= 5]
        bull = sorted([c for c in cands if c[1]["bias"] == "Bullish"], key=lambda c: (-c[1]["win_rate"], -c[1]["avg"]))
        bear = sorted([c for c in cands if c[1]["bias"] == "Bearish"], key=lambda c: (c[1]["win_rate"], c[1]["avg"]))
        pack = lambda c: {**c[1], "month_name": c[1]["name"], "key": c[0]["key"], "name": c[0]["name"],  # noqa: E731
                          "mode": c[0]["mode"]}
        return {"month": m, "name": sx.MONTHS[m - 1], "bullish": [pack(c) for c in bull[:8]],
                "bearish": [pack(c) for c in bear[:8]]}

    out = {"view": "monthly", "years": years, "today": today.isoformat(), "groups": GROUPS, "assets": rows,
           "this_month": leaders(today.month), "next_month": leaders(today.month % 12 + 1),
           "lookbacks": list(LOOKBACKS)}
    _CACHE.clear()
    _CACHE[ck] = out
    return out


def weekly_overview(db: Session, years: int = 10, today: date | None = None) -> dict:
    today = today or date.today()
    ck = ("weekly", years, today.isoformat(), _latest_marker(db))
    if ck in _CACHE:
        return _CACHE[ck]
    w0 = sx.week_of(today)
    wanted = [(w0 - 1 + i) % 52 + 1 for i in range(4)]
    rows = []
    for key, (name, group, _, _, mode, note) in ASSETS.items():
        obs = _obs(db, key)
        daily = len(obs) > 400 and (obs[-1][0] - obs[-200][0]).days < 400
        if not daily:
            rows.append({"key": key, "name": name, "group": group, "mode": mode, "note": note, "weeks": [],
                         "daily": False})
            continue
        stats = sx.week_stats(sx.weekly_moves(obs, mode, today), years, today)
        picked = []
        for w in wanted:
            st = stats[w - 1]
            st["bias"] = sx.bias(st)
            picked.append(st)
        rows.append({"key": key, "name": name, "group": group, "mode": mode, "note": note, "weeks": picked,
                     "daily": True})

    def leaders(i: int) -> dict:
        w = wanted[i]
        cands = [(r, r["weeks"][i]) for r in rows if r["weeks"] and r["weeks"][i]["n"] >= 5]
        bull = sorted([c for c in cands if c[1]["bias"] == "Bullish"], key=lambda c: (-c[1]["win_rate"], -c[1]["avg"]))
        bear = sorted([c for c in cands if c[1]["bias"] == "Bearish"], key=lambda c: (c[1]["win_rate"], c[1]["avg"]))
        pack = lambda c: {**c[1], "period_name": c[1]["name"], "key": c[0]["key"], "name": c[0]["name"],  # noqa: E731
                          "mode": c[0]["mode"]}
        return {"week": w, "name": sx.week_label(w, today.year), "bullish": [pack(c) for c in bull[:8]],
                "bearish": [pack(c) for c in bear[:8]]}

    out = {"view": "weekly", "years": years, "today": today.isoformat(), "groups": GROUPS, "assets": rows,
           "columns": [sx.week_label(w, today.year) for w in wanted], "week_now": w0,
           "this_week": leaders(0), "next_week": leaders(1), "lookbacks": list(LOOKBACKS)}
    _CACHE.clear()
    _CACHE[ck] = out
    return out
