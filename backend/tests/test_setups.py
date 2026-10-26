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
