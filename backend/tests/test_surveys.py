from app.services import surveys


def test_analyse_pmi_and_confidence():
    a = surveys.analyse("mpmi", 51.2, 49.5, 50.0, [48, 49, 49.5])
    assert a["signals"] == {"momentum": 1, "surprise": 1, "level": 1} and a["lean"] == "Bullish"
    assert "crossed into expansion" in a["read"].lower()
    b = surveys.analyse("spmi", 48.0, 49.0, None, [])
    assert b["signals"]["level"] == -1 and b["lean"] == "Bearish" and b["surprise"] is None
    c = surveys.analyse("conf", -20.0, -22.0, -21.0, [-25, -24, -23])
    assert c["signals"] == {"momentum": 1, "surprise": 1, "level": 1}


def test_board_and_edit(client, db):
    r = client.get("/api/macro/surveys")
    assert r.status_code == 200
    d = r.json()
    names = {x["indicator"] for x in d["kinds"]["mpmi"]["rows"]}
    assert {"US_ISM_MANUF", "CN_CAIXIN_MANUF_PMI", "NZ_MANUF_PMI", "CA_MANUF_PMI", "CA_IVEY_PMI"} <= names
    assert {"AU_CONSUMER_CONF", "JP_CONSUMER_CONF"} <= {x["indicator"] for x in d["kinds"]["conf"]["rows"]}
    assert client.patch("/api/macro/surveys/NZ_MANUF_PMI", json={"value": "48.7", "period": "2026-08"}).status_code == 200
    r = client.patch("/api/macro/surveys/NZ_MANUF_PMI", json={"value": "51.2", "period": "2026-09"})
    assert r.status_code == 200, r.text
    nz = next(x for x in client.get("/api/macro/surveys").json()["kinds"]["mpmi"]["rows"] if x["indicator"] == "NZ_MANUF_PMI")
    assert nz["actual"] == 51.2 and nz["previous"] == 48.7 and nz["signals"]["level"] == 1
    assert client.patch("/api/macro/surveys/NZ_MANUF_PMI", json={"value": "x", "period": "2026-09"}).status_code == 400
    assert client.patch("/api/macro/surveys/US_CPI_YOY", json={"value": "3", "period": "2026-09"}).status_code == 404
    rows = client.get("/api/macro/heatmap?currency=NZD").json()["rows"]
    assert any(x["indicator"] == "NZ_MANUF_PMI" for x in rows)


def test_heatmap_scores_surveys(client, db):
    hm = client.get("/api/macro/heatmap?currency=NZD").json()
    row = next(x for x in hm["rows"] if x["indicator"] == "NZ_MANUF_PMI")
    assert row["actual"] is None and row["survey"] == "mpmi" and hm["currency_bullish_pct"] is None
    client.patch("/api/macro/surveys/NZ_MANUF_PMI", json={"value": "48.0", "period": "2026-08"})
    client.patch("/api/macro/surveys/NZ_MANUF_PMI", json={"value": "52.0", "period": "2026-09"})
    hm = client.get("/api/macro/heatmap?currency=NZD").json()
    row = next(x for x in hm["rows"] if x["indicator"] == "NZ_MANUF_PMI")
    assert row["currency_impact"] == "Bullish" and row["stocks_impact"] == "Bullish" and row["previous"] == 48.0
    assert hm["currency_bullish_pct"] == 100.0


def test_heatmap_edit_any_indicator(client, db):
    rows = client.get("/api/macro/heatmap?currency=ZAR").json()["rows"]
    gdp = next(x for x in rows if x["indicator"] == "ZA_GDP_QOQ")
    assert gdp["actual"] is None and gdp["edit_period"].startswith("20")
    r = client.patch("/api/macro/indicators/ZA_GDP_QOQ", json={"field": "forecast", "value": "0.4", "period": "2026Q2"})
    assert r.status_code == 200, r.text
    r = client.patch("/api/macro/indicators/ZA_GDP_QOQ", json={"field": "actual", "value": "0.6", "period": "2026Q2"})
    assert r.status_code == 200, r.text
    gdp = next(x for x in client.get("/api/macro/heatmap?currency=ZAR").json()["rows"] if x["indicator"] == "ZA_GDP_QOQ")
    assert gdp["actual"] == 0.6 and gdp["forecast"] == 0.4 and gdp["currency_impact"] == "Bullish"
    r = client.patch("/api/macro/indicators/ZA_GDP_QOQ", json={"field": "forecast", "value": "0.8", "period": "2026Q2"})
    gdp = next(x for x in client.get("/api/macro/heatmap?currency=ZAR").json()["rows"] if x["indicator"] == "ZA_GDP_QOQ")
    assert gdp["forecast"] == 0.8 and gdp["currency_impact"] == "Bearish"
    assert client.patch("/api/macro/indicators/ZA_GDP_QOQ", json={"field": "actual", "value": "1", "period": "2026-09"}).status_code == 400
    assert client.patch("/api/macro/indicators/NOPE", json={"field": "actual", "value": "1"}).status_code == 404


def test_new_gdp_and_core_rows(client):
    for ccy, codes in {"CAD": ["CA_GDP_YOY", "CA_CORE_CPI_TRIM_YOY", "CA_CORE_CPI_MEDIAN_YOY"],
                       "AUD": ["AU_GDP_YOY", "AU_CORE_TRIMMED_MEAN_YOY"], "CHF": ["CH_GDP_YOY", "CH_CORE_CPI_YOY"],
                       "CNY": ["CN_GDP_YOY", "CN_CORE_CPI_YOY"], "MXN": ["MX_GDP_YOY", "MX_CORE_CPI_YOY"],
                       "NZD": ["NZ_GDP_YOY", "NZ_CORE_CPI_YOY"], "USD": ["US_GDP_YOY"], "EUR": ["EA_GDP_YOY"],
                       "GBP": ["GB_GDP_YOY"], "JPY": ["JP_GDP_YOY"], "ZAR": ["ZA_GDP_YOY"]}.items():
        rows = {r["indicator"] for r in client.get(f"/api/macro/heatmap?currency={ccy}").json()["rows"]}
        assert set(codes) <= rows, (ccy, set(codes) - rows)
    r = client.patch("/api/macro/indicators/CA_CORE_CPI_TRIM_YOY", json={"field": "actual", "value": "2.9", "period": "2026-09"})
    assert r.status_code == 200, r.text
