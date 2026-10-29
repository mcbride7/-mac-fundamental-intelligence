import math
from datetime import date, timedelta

from app.analytics import seasonality as sx
from app.services import seasonality as ss

TODAY = date(2026, 10, 26)


def _history(start=date(2010, 1, 1), end=TODAY, december_rally=True):
    """Flat-ish prices that always rise in December and fall in September."""
    obs, v, d = [], 100.0, start
    while d <= end:
        if d.weekday() < 5:
            if december_rally and d.month == 12:
                v *= 1.002
            elif d.month == 9:
                v *= 0.999
            else:
                v *= 1 + 0.0002 * math.sin(d.toordinal())
            obs.append((d, round(v, 5)))
        d += timedelta(days=1)
    return obs


def test_month_stats_find_the_pattern():
    moves = sx.monthly_moves(_history(), "pct", TODAY)
    assert (2026, 10) not in moves  # unfinished month left out
    st = sx.month_stats(moves, 10, TODAY)
    dec, sep = st[11], st[8]
    assert dec["n"] == 10 and dec["win_rate"] == 100 and dec["avg"] > 3 and sx.bias(dec) == "Bullish"
    assert sep["win_rate"] == 0 and sep["avg"] < 0 and sx.bias(sep) == "Bearish"
    grid = sx.year_grid(moves, 3, TODAY)
    assert grid[0]["year"] == 2026 and grid[0]["months"][9] is None and grid[1]["months"][11] > 3


def test_bp_mode_path_and_forward_window():
    obs = [(d, 4 + (0.5 if d.month >= 7 else 0)) for d, _ in _history()]
    moves = sx.monthly_moves(obs, "bp", TODAY)
    assert sx.month_stats(moves, 10, TODAY)[6]["avg"] == 50.0  # +50 bp every July
    p = sx.seasonal_path(_history(), 10, "pct", TODAY)
    assert p["years_used"] == 10 and p["average"][-1] > 1.5 and p["average"][-1] > p["average"][40] and len(p["current"]) <= len(p["average"])
    fw = sx.forward_window(_history(), 10, 30, "pct", date(2026, 11, 25))
    assert fw["n"] == 10 and fw["win_rate"] == 100


def test_api_overview_and_asset(client, db):
    ss._store(db, "XAUUSD", _history())
    ss._store(db, "US10Y", [(d, 4 + 0.001 * i) for i, (d, _) in enumerate(_history())])
    o = client.get("/api/seasonality?years=10").json()
    assert len(o["assets"]) == len(ss.ASSETS)
    gold = next(a for a in o["assets"] if a["key"] == "XAUUSD")
    assert gold["months"][11]["bias"] == "Bullish" and gold["years_of_data"] > 16
    assert o["this_month"]["name"] in sx.MONTHS
    leaders = o["this_month"]["bullish"] + o["this_month"]["bearish"] + o["next_month"]["bullish"] + o["next_month"]["bearish"]
    assert all(x["name"] not in sx.MONTHS for x in leaders)
    a = client.get("/api/seasonality/XAUUSD?years=5").json()
    assert a["months"][11]["n"] == 5 and a["path"] and a["next_30"] and a["grid"][0]["year"] == date.today().year
    assert client.get("/api/seasonality/US10Y").json()["mode"] == "bp"
    assert client.get("/api/seasonality/NOPE").status_code == 404


def test_weekly_stats_and_price_chart(client, db):
    obs = _history()
    wm = sx.weekly_moves(obs, "pct", TODAY)
    ws = sx.week_stats(wm, 10, TODAY)
    assert len(ws) == 52 and ws[50]["win_rate"] == 100 and ws[37]["win_rate"] == 0  # mid-Dec up, mid-Sep down
    assert ws[0]["name"].startswith("W1 (")
    ss._store(db, "XAUUSD", obs)
    a = client.get("/api/seasonality/XAUUSD?years=10").json()
    assert len(a["weeks"]) == 52 and a["this_week"]["week"] == a["week_now"]
    pc = a["price_chart"]
    assert pc and len(pc["seasonal"]) == len(pc["dates"]) and pc["actual"][-1] is not None
    assert pc["projection"][pc["today_index"]] == pc["latest"] and "seasonal path" in pc["note"]
    w = client.get("/api/seasonality?years=10&view=weekly").json()
    gold = next(x for x in w["assets"] if x["key"] == "XAUUSD")
    assert w["view"] == "weekly" and len(gold["weeks"]) == 4 and len(w["columns"]) == 4
    assert client.get("/api/seasonality?view=daily").status_code == 422


def test_equity_indices_listed(client, db):
    from datetime import date, timedelta

    from app.services import seasonality as ss

    for k in ("NIKKEI", "EUROSTOXX50", "ASHR", "SPX", "NASDAQ", "NASDAQ100", "DJIA", "RUSSELL2000"):
        assert ss.ASSETS[k][1] == "Equities"
    obs, d, v = [], date(2012, 1, 2), 100.0
    while d < date(2026, 10, 1):
        obs.append((d, v)); d += timedelta(days=1); v *= 1.0003
    ss._store(db, "NIKKEI", obs)
    ss._CACHE.clear()
    a = client.get("/api/seasonality/NIKKEI").json()
    assert a["name"] == "Nikkei 225" and a["group"] == "Equities"
