from datetime import datetime, timezone

from app.services import heatmap as hm


def test_calls():
    assert hm.currency_call(0.1, "hawkish") == "Bullish"          # hot CPI: dollar up
    assert hm.stocks_call("Bullish", "inflation") == "Bearish"     # ...stocks down
    assert hm.currency_call(0.1, "dovish") == "Bearish"            # unemployment up: dollar down
    assert hm.stocks_call("Bearish", "employment") == "Bearish"    # ...stocks down too
    assert hm.currency_call(-6, "dovish") == "Bullish"             # fewer jobless claims: dollar up
    assert hm.currency_call(0.0, "hawkish") == "Neutral" and hm.currency_call(None, "hawkish") == "Neutral"


def _release(db, code, period, actual, consensus, previous=None):
    from app.models import EconomicEvent
    from app.services import data_access as da
    from app.services import manual_service as ms

    ind = da.indicator_by_code(db, code)
    ev = EconomicEvent(indicator_id=ind.id, reference_period=period, importance=ind.importance,
                       consensus=consensus, previous=previous,
                       scheduled_at=datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc))
    db.add(ev)
    db.commit()
    ms.quick_edit_event(db, ev.id, "actual", actual, reason="test")
    return ev


def test_heatmap_scores_and_pairs(client, db):
    _release(db, "US_CPI_YOY", "2026-09", 3.7, 3.6, 3.4)            # Bullish USD, Bearish stocks
    _release(db, "US_UNEMPLOYMENT", "2026-09", 4.2, 4.1, 4.1)       # Bearish USD, Bearish stocks
    _release(db, "US_RETAIL_SALES_MOM", "2026-09", 0.8, 0.3, 1.2)   # Bullish both
    _release(db, "EA_HICP_YOY", "2026-09", 2.0, 2.2, 2.1)           # Bearish EUR
    d = client.get("/api/macro/heatmap?currency=USD").json()
    calls = {r["indicator"]: (r["currency_impact"], r["stocks_impact"], round(r["surprise"], 2)) for r in d["rows"]}
    assert calls["US_CPI_YOY"] == ("Bullish", "Bearish", 0.1)
    assert calls["US_UNEMPLOYMENT"] == ("Bearish", "Bearish", 0.1)
    assert calls["US_RETAIL_SALES_MOM"] == ("Bullish", "Bullish", 0.5)
    assert d["currency_score"] == 1 and d["stocks_score"] == -1
    assert d["currency_bullish_pct"] == 66.67 and d["stocks_bullish_pct"] == 33.33
    eurusd = next(p for p in d["pairs"] if p["pair"] == "EURUSD")
    assert eurusd["score"] == -1 - 1  # EUR -1 minus USD +1
    gold = next(a for a in d["assets"] if a["asset"] == "GOLD")
    assert gold["score"] == -1
    assert {t["currency"] for t in d["tabs"]} == set(hm.CURRENCIES)
    assert client.get("/api/macro/heatmap?currency=XYZ").status_code == 404


def test_weekly_claims_period():
    from app.ingestion.forexfactory import parse_value, reference_period

    thu = datetime(2026, 10, 22, 12, 30, tzinfo=timezone.utc)
    assert reference_period("weekly", thu, "Unemployment Claims") == "2026-10-17"
    assert parse_value("7.08M", "m") == 7.08 and parse_value("194K", "k") == 194


def test_regime_history_lists_changes_only(client, db):
    from datetime import timedelta

    from app.models import MacroRegime

    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i, (p, s) in enumerate([("GROWTH", None), ("GROWTH", None), ("STAGFLATION", "Risk-off"),
                                ("STAGFLATION", "Risk-off"), ("GROWTH", None)]):
        db.add(MacroRegime(as_of=t0 + timedelta(days=i), primary=p, secondary=s, confidence=60, signals={}, explanation=[]))
    db.commit()
    h = client.get("/api/macro/regime").json()["history"]
    seq = [(x["primary"], x["readings"]) for x in h[:3]]
    assert seq == [("GROWTH", 1), ("STAGFLATION", 2), ("GROWTH", 2)]
    assert h[1]["started_at"].startswith("2026-10-03") and h[1]["ended_at"].startswith("2026-10-05")
