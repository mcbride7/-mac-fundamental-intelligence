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
