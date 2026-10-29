from app.analytics.decision import parse_decision

FED_HOLD = ("Recent indicators suggest that economic activity has continued to expand at a moderate pace. "
            "In support of its goals, the Committee decided to maintain the target range for the federal funds rate "
            "at 3-3/4 to 4 percent. In considering the extent and timing of additional adjustments...")
FED_CUT = ("... In support of its goals and in light of the shift in the balance of risks, the Committee decided to lower "
           "the target range for the federal funds rate by 1/4 percentage point to 3-1/2 to 3-3/4 percent.")
BOE = "At its meeting ending on 5 November 2026, the MPC voted by a majority of 7-2 to maintain Bank Rate at 4%."
ECB = ("The Governing Council today decided to keep the three key ECB interest rates unchanged. ... "
       "the deposit facility, the main refinancing operations and the marginal lending facility will remain unchanged at 2.00%, 2.15% and 2.40%")
RBA = "At its meeting today, the Board decided to lower the cash rate target by 25 basis points to 3.35 per cent."


def test_parse_decisions():
    assert parse_decision(FED_HOLD) == ("HOLD", 4.0)
    assert parse_decision(FED_CUT) == ("CUT", 3.75)
    assert parse_decision(BOE) == ("HOLD", 4.0)
    assert parse_decision(ECB) == ("HOLD", 2.0)
    assert parse_decision(RBA) == ("CUT", 3.35)
    assert parse_decision("Speech on productivity and the labour market.") == (None, None)


def test_statement_updates_overview(client, db):
    from datetime import datetime, timezone

    from app.models import CentralBankStatement
    from app.services import cb_decision
    from app.services import data_access as da

    # rate history: the Fed cut in September, then held
    for per, v in (("2026-07", 4.25), ("2026-08", 4.25), ("2026-09", 4.0), ("2026-10", 4.0)):
        assert client.patch("/api/macro/indicators/US_FED_RATE", json={"field": "actual", "value": str(v), "period": per,
                                                                       "reason": "test"}).status_code == 200
    before = client.get("/api/central-banks/FED").json()
    assert before["last_decision"] == "CUT"
    cb = da.cb_by_code(db, "FED")
    st = CentralBankStatement(central_bank_id=cb.id, doc_type="statement", title="FOMC statement",
                              published_at=datetime(2026, 10, 28, 18, tzinfo=timezone.utc),
                              meeting_date=datetime(2026, 10, 28).date(), text=FED_HOLD, sha256="x1",
                              input_method="automated", verification_status="VERIFIED")
    db.add(st)
    db.commit()
    assert cb_decision.record_from_statement(db, st)["decision"] == "HOLD"
    d = client.get("/api/central-banks/FED").json()
    assert d["last_decision"] == "HOLD" and d["last_change_bps"] == 0 and d["current_rate"] == 4.0
    assert d["last_decision_date"].startswith("2026-10-28")
    # and it can be typed over by hand
    r = client.patch("/api/central-banks/FED/overview", json={"field": "last_decision", "value": "CUT"})
    assert r.status_code == 200, r.text
    assert client.get("/api/central-banks/FED").json()["last_decision"] == "CUT"
