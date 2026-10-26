from datetime import date

from app.analytics import setups as st


def test_pillar_scores():
    assert st.central_bank_score(70, 50, 60, 10) > 1        # hawkish statements, hikes priced
    assert st.central_bank_score(30, -75, 0, 80) < -1
    assert st.economic_score(4.0, 2.0, 3, 5) > 1            # inflation 2pp over target, hawkish surprises
    assert st.cot_score(95, 80, 1000) == -1.0 and st.cot_score(5, 20, -1) == 1.0   # crowded: contrarian
    assert st.cot_score(70, 50, 100) > 0.5                   # rising, not crowded: follow
    assert st.retail_score(75) == -1.25 and st.retail_score(30) == 1.0
    m = {"n": 10, "avg": 1.2, "win_rate": 80}
    assert st.seasonality_score(m, [m, {"n": 2, "avg": 1, "win_rate": 100}]) > 1


def test_combine_grades_and_reasons():
    s = st.combine("EURUSD", {"central_bank": 1.6, "economic": 1.4, "cot": 0.8, "seasonality": 0.6, "retail": 1.2},
                   {"central_bank": "ECB more hawkish than Fed"})
    assert s.direction == "LONG" and s.grade == "A+" and s.reasons[0] == "ECB more hawkish than Fed"
    mixed = st.combine("USDJPY", {"central_bank": 1.0, "economic": -1.0, "cot": 0.5, "seasonality": -0.5, "retail": None})
    assert mixed.grade in ("No setup", "C") and mixed.coverage == 0.85
    thin = st.combine("USDMXN", {"central_bank": 2, "economic": None, "cot": None, "seasonality": None, "retail": None})
    assert thin.grade == "Not enough data" and thin.direction == "NONE"


def test_api_ranks_and_retail_entry(client, db):
    from app.services import setups as sv

    d = client.get("/api/setups").json()
    assert len(d["setups"]) == len(sv.PAIRS) and {"central_bank", "retail"} <= set(d["weights"])
    eur = next(x for x in d["setups"] if x["asset"] == "EURUSD")
    cot_p = next(p for p in eur["pillars"] if p["key"] == "cot")
    assert cot_p["score"] is not None and "EUR index" in cot_p["note"]  # bundled COT history is used
    r = client.put("/api/setups/retail/EUR/USD", json={"long_pct": 78})
    assert r.status_code in (200, 404)
    r = client.put("/api/setups/retail/EURUSD", json={"long_pct": 78})
    assert r.status_code == 200 and r.json()["source"] == "manual"
    eur = next(x for x in client.get("/api/setups").json()["setups"] if x["asset"] == "EURUSD")
    ret = next(p for p in eur["pillars"] if p["key"] == "retail")
    assert ret["score"] == -1.4 and eur["retail_long_pct"] == 78
    assert client.put("/api/setups/retail/EURUSD", json={"long_pct": 140}).status_code == 400
    assert client.get("/api/setups?limit=3").json()["setups"].__len__() == 3


def test_table_columns_and_scores(client, db):
    from datetime import datetime, timezone

    from app.models import EconomicEvent
    from app.services import data_access as da
    from app.services import manual_service as ms
    from app.services import setups_table as tb

    assert tb.column_of("US_ISM_MANUF", "business") == "mpmi" and tb.column_of("US_CORE_CPI_YOY", "inflation") is None
    assert tb.column_of("GB_CLAIMANT", "employment") == "claims" and tb.column_of("EA_HICP_YOY", "inflation") == "cpi"
    assert tb.column_of("AU_EMPLOYMENT_CHANGE", "employment") == "nfp" and tb.column_of("US_FED_RATE", "monetary_policy") is None
    assert tb.bias_of(9) == "Very Bullish" and tb.bias_of(4) == "Bullish" and tb.bias_of(-3) == "Neutral"
    for code, a, f in (("GB_CPI_YOY", 3.9, 3.7), ("US_CPI_YOY", 2.9, 3.1)):
        ind = da.indicator_by_code(db, code)
        ev = EconomicEvent(indicator_id=ind.id, reference_period="2026-09", importance="high", consensus=f,
                           scheduled_at=datetime(2026, 10, 15, 8, tzinfo=timezone.utc))
        db.add(ev)
        db.commit()
        ms.quick_edit_event(db, ev.id, "actual", a, reason="test")
    tb.clear_cache()
    d = client.get("/api/setups/table").json()
    keys = [c["key"] for g in d["groups"] for c in g["columns"]]
    assert keys[:4] == ["trend", "seasonality", "cot", "crowd"] and "jolts" in keys
    rows = {r["symbol"]: r for r in d["rows"]}
    assert rows["GBPUSD"]["cells"]["cpi"] == 2      # UK CPI beat, US CPI missed
    assert rows["XAUUSD"]["cells"]["cpi"] == 1      # soft US inflation supports gold
    assert rows["EURGBP"]["cells"]["cpi"] == -1
    assert all(-2 <= v <= 2 for r in d["rows"] for v in r["cells"].values() if v is not None)
    assert rows["GBPUSD"]["score"] == sum(v for v in rows["GBPUSD"]["cells"].values() if v is not None)
    assert len(d["rows"]) == len(tb.MAJORS + tb.CROSSES + tb.EM) + len(tb.OTHER)
