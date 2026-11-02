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
