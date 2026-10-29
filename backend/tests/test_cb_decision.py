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


def test_dissent_and_characterise():
    from app.analytics.decision import characterise, parse_dissent

    boe = ("The MPC voted by a majority of 7-2 to maintain Bank Rate at 4%. Two members voted to reduce Bank Rate "
           "by 0.25 percentage points, to 3.75%.")
    d = parse_dissent(boe)
    assert d["dovish"] == 2 and d["hawkish"] == 0 and d["split"] == "7-2"
    fed = ("Voting against the action was Jane Doe, who preferred to raise the target range for the federal funds rate "
           "by 1/4 percentage point at this meeting.")
    assert parse_dissent(fed)["hawkish"] == 1
    hh = characterise("HOLD", tone_now=30, tone_prev=10, dissent={"hawkish": 1, "dovish": 0, "split": None},
                      prob_cut=60, prob_hike=0, inflation=3.2, target=2.0)
    assert hh["label"] == "Hawkish hold" and hh["lean"] == "hawkish" and any("surprise" in r for r in hh["reasons"])
    dh = characterise("HOLD", tone_now=-25, tone_prev=0, dissent=d, inflation=1.8, target=2.0)
    assert dh["label"] == "Dovish hold"
    nh = characterise("HOLD", tone_now=2, tone_prev=0, dissent={"hawkish": 0, "dovish": 0, "split": None})
    assert nh["label"] == "Neutral hold"
    assert characterise("CUT", tone_now=20, tone_prev=0, dissent={"hawkish": 2, "dovish": 0, "split": None})["label"] == "Hawkish cut"


def test_overview_shows_read(client, db):
    from datetime import datetime, timezone

    from app.models import CentralBankStatement
    from app.services import cb_decision
    from app.services import data_access as da

    cb = da.cb_by_code(db, "BOE")
    for i, (txt, day) in enumerate([("The MPC voted unanimously to maintain Bank Rate at 4%. Inflation is falling.", 18),
                                    ("The MPC voted by a majority of 7-2 to maintain Bank Rate at 4%. Two members voted "
                                     "to reduce Bank Rate. Disinflation is under way and the labour market is loosening.", 28)]):
        st = CentralBankStatement(central_bank_id=cb.id, doc_type="statement", title=f"MPS {i}",
                                  published_at=datetime(2026, 9 + i, day, 12, tzinfo=timezone.utc),
                                  meeting_date=datetime(2026, 9 + i, day).date(), text=txt, sha256=f"boe{i}",
                                  input_method="automated", verification_status="VERIFIED", tone_score=[5.0, -20.0][i])
        db.add(st)
        db.commit()
        cb_decision.record_from_statement(db, st)
    d = client.get("/api/central-banks/BOE").json()
    assert d["last_decision"] == "HOLD"
    assert d["decision_read"]["label"] == "Dovish hold", d["decision_read"]
    assert any("Vote split 7-2" in r for r in d["decision_read"]["reasons"])
