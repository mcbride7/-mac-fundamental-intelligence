import io
import json
import zipfile
from datetime import date

from app.analytics import cot as ca
from app.services import cot


def _api_row(code, d, oi, ncl, ncs, cl, cs):
    return {"cftc_contract_market_code": code, "report_date_as_yyyy_mm_dd": f"{d}T00:00:00.000",
            "open_interest_all": str(oi), "noncomm_positions_long_all": str(ncl), "noncomm_positions_short_all": str(ncs),
            "comm_positions_long_all": str(cl), "comm_positions_short_all": str(cs),
            "nonrept_positions_long_all": "10", "nonrept_positions_short_all": "20", "market_and_exchange_names": "X"}


def test_index_and_signals():
    vals = list(range(0, 100, 2))  # rising every week: latest = top of the range
    assert ca.cot_index(vals, 52) == 100.0 and ca.cot_index(vals[:-10] + [0], 52) == 0.0
    rows = [{"ncl": 100 + i * 10, "ncs": 50, "cl": 50, "cs": 100 + i * 10, "nrl": 1, "nrs": 1, "oi": 1000 + i,
             "price": 100 + i} for i in range(30)]
    kinds = {s["kind"] for s in ca.signals(rows)}
    assert "crowded_long" in kinds and "comm_extreme_short" in kinds and "oi_confirm" in kinds


def test_bundled_history_loads_on_start(client, db):
    d = client.get("/api/cot").json()
    gold = next(m for m in d["markets"] if m["code"] == "088691")
    assert gold["weeks"] >= 90 and gold["report_date"] == "2026-10-13"
    assert gold["spec_net"] == gold["spec_net"] and 0 <= gold["cot_index_52"] <= 100
    assert len(d["markets"]) == 19
    m = client.get("/api/cot/088691?weeks=13").json()
    assert len(m["series"]) == 13 and m["series"][-1]["d"] == "2026-10-13"


def test_cftc_fetch_and_prices(client, db, monkeypatch):
    from app.models import IndicatorObservation

    class R:
        def __init__(self, rows): self.rows = rows
        def json(self): return self.rows

    rows = [_api_row("088691", "2026-10-20", 500000, 300000, 40000, 90000, 400000),
            _api_row("999999", "2026-10-20", 1, 1, 1, 1, 1)]  # not tracked: ignored
    monkeypatch.setattr(cot, "http_get", lambda url, params=None, retries=2: R(rows))
    monkeypatch.setattr(cot, "_collect_price_series", lambda db: [])
    db.add(IndicatorObservation(series="COTPX:DEXJPUS", obs_date=date(2026, 10, 13), value=150.0))
    db.add(IndicatorObservation(series="RISK:gold", obs_date=date(2026, 10, 19), value=2500.0))
    db.commit()
    src = db.query(cot.Source).filter_by(key="cftc").one()
    assert cot.run_cftc(db, src) == 1
    g = client.get("/api/cot/088691?weeks=2").json()
    assert g["report_date"] == "2026-10-20" and g["spec_net"] == 260000
    assert g["series"][-1]["price"] == 2500.0 and g["series"][-1]["price_source"] == "Twelve Data"
    jpy = client.get("/api/cot/097741?weeks=1").json()["series"][-1]
    assert abs(jpy["price"] - 1 / 150) < 1e-9  # USD per JPY, so a rising line = stronger yen
    assert cot.run_cftc(db, src) == 0  # nothing new the second time


def test_file_import_and_hand_edits(client, db):
    header = ["Market and Exchange Names", "As of Date in Form YYYY-MM-DD", "CFTC Contract Market Code",
              "Open Interest (All)", "Noncommercial Positions-Long (All)", "Noncommercial Positions-Short (All)",
              "Commercial Positions-Long (All)", "Commercial Positions-Short (All)",
              "Nonreportable Positions-Long (All)", "Nonreportable Positions-Short (All)"]
    line = ["SOUTH AFRICAN RAND", "2026-10-20", "122741", "30,000", "20000", "5000", "4000", "21000", "100", "200"]
    buf = io.StringIO()
    buf.write(",".join(header) + "\n" + ",".join(f'"{x}"' for x in line) + "\n")
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("annual.txt", buf.getvalue())
    r = client.post("/api/cot/import", files={"file": ("deacot2026.zip", z.getvalue(), "application/zip")})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1
    zar = client.get("/api/cot/122741?weeks=1").json()
    assert zar["spec_net"] == 15000 and zar["oi"] == 30000
    r = client.put("/api/cot/122741/weeks/2026-10-20/price", json={"price": 0.0555})
    assert r.json()["price_source"] == "manual"
    r = client.post("/api/cot/122741/prices", json={"text": "2026-10-15, 0.0561\nnot a line\n2020-01-01, 1"})
    assert r.json()["saved"] == 1 and len(r.json()["skipped"]) == 2
    assert client.post("/api/cot/import", files={"file": ("x.csv", b"a,b\n1,2", "text/csv")}).status_code == 400
