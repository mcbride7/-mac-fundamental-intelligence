from datetime import date

from app.ingestion import yields

ECB = """KEY,FREQ,REF_AREA,CURRENCY,PROVIDER_FM,INSTRUMENT_FM,PROVIDER_FM_ID,DATA_TYPE_FM,TIME_PERIOD,OBS_VALUE
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_2Y,2026-10-26,1.9412
YC.B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y,B,U2,EUR,4F,G_N_A,SV_C_YM,SR_2Y,2026-10-27,1.9655
"""
BOE = """DATE,IUDSNPY
26 Oct 2026,3.8123
27 Oct 2026,3.7901
"""


def test_parsers():
    assert yields.parse_ecb_csv(ECB) == [(date(2026, 10, 26), 1.9412), (date(2026, 10, 27), 1.9655)]
    assert yields.parse_boe_csv(BOE, "IUDSNPY")[-1] == (date(2026, 10, 27), 3.7901)
    import pytest
    with pytest.raises(Exception):
        yields.parse_boe_csv("<html>error</html>", "IUDSNPY")


def test_run_and_proxy(client, db, monkeypatch):
    from app.engines import fundamentals as fnd

    monkeypatch.setattr(yields, "fetch_ecb", lambda t: yields.parse_ecb_csv(ECB) if t == "2Y" else [])
    monkeypatch.setattr(yields, "fetch_boe", lambda t: yields.parse_boe_csv(BOE, "IUDSNPY") if t == "5Y" else [])
    r = client.post("/api/sources/yields/run")
    assert r.status_code == 200 and r.json()["status"] == "OK" and r.json()["records"] == 4, r.text
    assert fnd.latest_yield(db, "DE", "2Y").yield_pct == 1.9655
    assert client.patch("/api/macro/indicators/GB_BOE_RATE", json={"field": "actual", "value": "4.0",
                                                                   "period": "2026-09"}).status_code == 200
    gb = fnd.build(db, "GBP")
    assert gb.policy_rate == 4.0 and gb.implied_is_proxy and gb.implied_tenor == "5Y"
    assert gb.implied_change_bps == round((3.7901 - 4.0) * 100)


BOC = {"observations": [{"d": "2026-10-26", "BD.CDN.2YR.DQ.YLD": {"v": "2.41"}},
                        {"d": "2026-10-27", "BD.CDN.2YR.DQ.YLD": {"v": "2.44"}}]}
RBA = """﻿F2 CAPITAL MARKET YIELDS - GOVERNMENT BONDS,,
Title,Australian Government 2 year bond,Australian Government 10 year bond
Description,Yields on Australian Government bonds,x
Frequency,Daily,Daily
Series ID,FCMYGBAG2D,FCMYGBAG10D
27-Oct-2026,3.512,4.301
28-Oct-2026,3.498,
"""
MOF = """Interest Rate (October 2026),,,
Date,1Y,2Y,10Y
2026/10/26,0.71,0.92,1.65
2026/10/27,0.72,0.94,1.67
"""
SNB = '''"CubeId";"rendoblid"
"PublishingDate";"2026-10-28 09:00"

"Date";"D0";"Value"
"2026-10-26";"1J";"0.12"
"2026-10-26";"2J";"0.18"
"2026-10-27";"2J";"0.21"
'''


def test_more_parsers():
    assert yields.parse_boc_json(BOC, "BD.CDN.2YR.DQ.YLD")[-1] == (date(2026, 10, 27), 2.44)
    assert yields.parse_rba_csv(RBA, "FCMYGBAG2D", "2 year") == [(date(2026, 10, 27), 3.512), (date(2026, 10, 28), 3.498)]
    assert yields.parse_rba_csv(RBA, "FCMYGBAG10D", "10 year") == [(date(2026, 10, 27), 4.301)]
    assert yields.parse_mof_csv(MOF, "2Y") == [(date(2026, 10, 26), 0.92), (date(2026, 10, 27), 0.94)]
    assert yields.parse_snb_csv(SNB, "2J") == [(date(2026, 10, 26), 0.18), (date(2026, 10, 27), 0.21)]


def test_partial_failure_warns(client, db, monkeypatch):
    def boom(t):
        raise RuntimeError("blocked")
    monkeypatch.setattr(yields, "fetch_ecb", lambda t: yields.parse_ecb_csv(ECB))
    for f in ("fetch_boe", "fetch_rba", "fetch_mof", "fetch_snb"):
        monkeypatch.setattr(yields, f, boom)
    monkeypatch.setattr(yields, "fetch_boc", lambda t: yields.parse_boc_json(BOC, "BD.CDN.2YR.DQ.YLD"))
    r = client.post("/api/sources/yields/run").json()
    assert r["status"] == "OK" and "Swiss National Bank" in r["warning"]
    src = next(s for s in client.get("/api/sources").json() if s["key"] == "yields")
    assert src is not None


def test_freshness_matches_schedule(db):
    from app.models import Source
    from app.seed import seed

    src = db.query(Source).filter_by(key="twelvedata").one()
    src.freshness_minutes = 15
    db.commit()
    seed(db)
    assert db.query(Source).filter_by(key="twelvedata").one().freshness_minutes == 60
