import math
import random
from datetime import date, datetime, time, timedelta, timezone


def _put(db, key, pts, prefix="SEAS:"):
    from app.models import IndicatorObservation

    for d, v in pts:
        db.add(IndicatorObservation(series=prefix + key, obs_date=d, value=v))


def test_relationships_and_column(client, db):
    from app.models import BondYield
    from app.services import intermarket as im
    from app.services import setups_table as tb

    random.seed(7)
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(260)]
    spread, eur, oil, cad, vix, spx = [], [], [], [], [], []
    s, o, v, x = -1.8, 70.0, 16.0, 5000.0
    for i, d in enumerate(days):
        s += random.gauss(0, 0.02); o *= math.exp(random.gauss(0, 0.015)); v = max(10, v + random.gauss(0, 0.6))
        x *= math.exp(random.gauss(0.0004, 0.008))
        spread.append(s); oil.append(o); vix.append(v); spx.append(x)
        eur.append(1.20 + 0.05 * s + random.gauss(0, 0.0004) + (0.03 if i == 259 else 0))  # last day: euro jumps above fair
        cad.append(1.75 - 0.005 * o + random.gauss(0, 0.0008))
    for d, sp in zip(days, spread):
        ts = datetime.combine(d, time(17), tzinfo=timezone.utc)
        db.add(BondYield(country="DE", tenor="2Y", ts=ts, yield_pct=2.0 + sp + 1.8, source="t"))
    _put(db, "US2Y", [(d, 2.0 + 1.8) for d in days])
    _put(db, "EURUSD", list(zip(days, eur)))
    _put(db, "WTI", list(zip(days, oil)))
    _put(db, "USDCAD", list(zip(days, cad)))
    _put(db, "VIX", list(zip(days, vix)))
    _put(db, "SPX", list(zip(days, spx)))
    db.commit()
    im.clear_cache()
    b = client.get("/api/intermarket").json()
    rel = {(r["pair"], r["driver"]): r for r in b["relationships"]}
    eu = rel[("EURUSD", "SPR:DE-US:2Y")]
    assert eu["status"] == "Working" and eu["corr"]["120"] > 0.3 and eu["z"] > 1.5 and "rich" in eu["note"]
    assert rel[("USDCAD", "WTI")]["status"] == "Working"
    assert any(o["pair"] == "EURUSD" for o in b["out_of_line"])
    assert b["regime"]["label"] and b["matrix"]["keys"] and b["leading"]
    assert b["confirmation"]["EURUSD"]["score"] <= 0  # rich vs its driver
    tb.clear_cache()
    rows = {r["symbol"]: r for r in tb.compute(db)["rows"]}
    assert "intermarket" in rows["EURUSD"]["cells"]
    assert rows["EURUSD"]["cells"]["intermarket"] == b["currency_scores"]["EUR"]
    assert client.get("/api/intermarket?window=20").json()["matrix"]["window"] == 20


def test_risk_divergence_bias_and_sections(client, db):
    from app.services import intermarket as im
    from app.services import setups_table as tb

    random.seed(11)
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(300)]
    spx, vix, us10, usd, gold, real = [], [], [], [], [], []
    x, v, y, u, g, r = 5000.0, 16.0, 4.0, 100.0, 2000.0, 1.8
    for i in range(300):
        late = i >= 280
        x *= math.exp(random.gauss(0.004 if late else 0, 0.006))      # stocks rally late
        v = max(9, v + random.gauss(-0.25 if late else 0, 0.4))       # vol falls
        y += random.gauss(0.03 if late else 0, 0.03)                   # yields up
        u *= math.exp(random.gauss(-0.004 if late else 0, 0.003))      # ...but the dollar falls -> divergence
        g *= math.exp(random.gauss(0.005 if late else 0, 0.006))
        r += random.gauss(0.0, 0.02)
        spx.append(x); vix.append(v); us10.append(y); usd.append(u); gold.append(g); real.append(r)
    _put(db, "SPX", list(zip(days, spx)))
    _put(db, "VIX", list(zip(days, vix)), prefix="RISK:")
    _put(db, "US10Y", list(zip(days, us10)))
    _put(db, "USD", list(zip(days, usd)))
    _put(db, "XAUUSD", list(zip(days, gold)))
    _put(db, "REAL10Y", list(zip(days, real)), prefix="IM:")
    db.commit()
    im.clear_cache(); tb.clear_cache()
    ld = im.Loader(db)
    assert im.zmove(ld, "SPX") > 1 and im.zmove(ld, "USD") < -1
    b = client.get("/api/intermarket").json()
    assert b["risk"]["label"] == "Risk-on" and b["risk"]["score"] >= 20 and b["risk"]["components"]
    titles = [d["title"] for d in b["divergences"]]
    assert "US yields and the dollar disagree" in titles
    d = next(d for d in b["divergences"] if d["title"] == "US yields and the dollar disagree")
    assert d["explanations"] and d["severity"] in ("Strong", "Moderate", "Mild")
    assert b["bias"] and isinstance(b["positioning"], list)
    for x in b["bias"]:
        assert x["direction"] in ("Bullish", "Bearish", "Neutral") and 0 <= x["strength"] <= 100
        assert set(x) >= {"supporting", "conflicting", "fundamentals", "catalysts", "invalidation"}
    assert b["bonds"]["us"][2]["tenor"] == "10Y" and b["bonds"]["us"][2]["yield"] is not None
    assert "Risk-on" in b["note"]
    n = client.post("/api/intermarket/ai-note").json()
    assert n["text"] and n["ai"] is False
