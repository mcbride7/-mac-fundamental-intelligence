from datetime import date


def _rate(client, code, pts):
    for per, v in pts:
        r = client.patch(f"/api/macro/indicators/{code}", json={"field": "actual", "value": str(v), "period": per,
                                                               "reason": "test"})
        assert r.status_code == 200, r.text


def test_support_rules():
    from app.services import cycles as cy

    assert cy.support("hiking", {"score": 0.5})["verdict"] == "Supported"
    assert cy.support("hiking", {"score": -0.5})["supported"] is False
    assert cy.support("cutting", {"score": -0.4})["verdict"] == "Supported"
    assert cy.support("holding", {"score": 0.1})["verdict"] == "Supported"
    assert cy.support("holding", {"score": 0.4})["verdict"] == "Hold, leaning to hike"


def test_board_finds_hiking_vs_cutting(client, db):
    from app.services import cycles as cy

    # BoJ hiking with hot inflation; ECB cutting with soft inflation
    _rate(client, "JP_BOJ_RATE", [("2026-03", 0.5), ("2026-04", 0.5), ("2026-08", 0.75), ("2026-09", 0.75)])
    _rate(client, "JP_CPI_YOY", [("2026-05", 2.6), ("2026-06", 2.9), ("2026-07", 3.1), ("2026-08", 3.3)])
    _rate(client, "EA_ECB_RATE", [("2026-03", 2.5), ("2026-04", 2.5), ("2026-07", 2.25), ("2026-09", 2.0)])
    _rate(client, "EA_HICP_YOY", [("2026-05", 2.0), ("2026-06", 1.8), ("2026-07", 1.6), ("2026-08", 1.4)])
    b = cy.board(db, today=date(2026, 10, 20))
    banks = {x["code"]: x for x in b["banks"]}
    assert banks["BOJ"]["cycle"]["stage"] == "hiking" and banks["BOJ"]["support"]["verdict"] == "Supported"
    assert banks["ECB"]["cycle"]["stage"] == "cutting" and banks["ECB"]["support"]["verdict"] == "Supported"
    p = next(x for x in b["pairs"] if {x["hawk"]["code"], x["dove"]["code"]} == {"BOJ", "ECB"})
    assert p["kind"] == "Hiking vs cutting" and p["confirmed"] and p["trade"] == "Short EUR/JPY"
    assert client.get("/api/central-banks/cycles").status_code == 200
