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
