from datetime import date, datetime, timezone

FED = """Transcript of Chair Powell's Press Conference October 28, 2026
CHAIR POWELL. Good afternoon. My colleagues and I remain squarely focused on our dual mandate goals. Inflation remains elevated
and we are not yet confident that it is moving sustainably to 2 percent. Today we decided to maintain our policy rate.
MICHELLE SMITH. Thank you. Nick.
NICK TIMIRAOS. Thank you, Chair Powell. Is a December rate cut a foregone conclusion?
CHAIR POWELL. A further reduction in the policy rate at the December meeting is not a foregone conclusion, far from it.
We are meeting by meeting. Inflation remains elevated and we will remain vigilant.
MICHELLE SMITH. Colby.
COLBY SMITH. Thanks. What about tariffs and inflation?
CHAIR POWELL. Tariffs are pushing up some goods prices. Inflation remains somewhat elevated. We are in no hurry."""


def test_analyse_transcript():
    from app.analytics import presser as pa

    r = pa.analyse(FED)
    assert r["questions"] == 2 and [q["who"] for q in r["qa"]] == ["NICK TIMIRAOS", "COLBY SMITH"]
    assert r["tone"] > 0 and r["label"] in ("Hawkish", "Leaning hawkish")
    ph = {p["phrase"] for p in r["phrases"]}
    assert {"not a foregone conclusion", "meeting by meeting", "vigilant"} <= ph
    assert r["topics"][0]["topic"] == "Inflation" and r["hawkish_quotes"]
    one = pa.split_turns("Plain text with no speakers at all. " * 20)
    assert len(one) == 1 and one[0]["role"] == "chair"


def test_store_compare_and_decision_read(client, db):
    from app.models import CentralBankStatement
    from app.services import cb_decision
    from app.services import data_access as da

    cb = da.cb_by_code(db, "FED")
    st = CentralBankStatement(central_bank_id=cb.id, doc_type="statement", title="FOMC statement",
                              published_at=datetime(2026, 10, 28, 18, tzinfo=timezone.utc), meeting_date=date(2026, 10, 28),
                              text="the Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4 percent.",
                              sha256="pc-st", input_method="automated", verification_status="VERIFIED", tone_score=0.0)
    db.add(st)
    db.commit()
    cb_decision.record_from_statement(db, st)
    r = client.post("/api/central-banks/FED/press-conferences", json={"text": FED, "held_on": "2026-10-28"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["questions"] == 2 and d["vs_statement"] is not None and d["vs_statement"] > 0
    lst = client.get("/api/central-banks/FED/press-conferences").json()
    assert lst["auto"] is True and lst["items"][0]["id"] == d["id"]
    assert client.get(f"/api/central-banks/FED/press-conferences/{d['id']}").json()["analysis"]["qa"]
    # same text again: not stored twice
    assert client.post("/api/central-banks/FED/press-conferences", json={"text": FED, "held_on": "2026-10-28"}).json()["id"] == d["id"]
    read = client.get("/api/central-banks/FED").json()["decision_read"]
    assert any("Press conference" in x for x in read["reasons"])
    assert client.post("/api/central-banks/FED/press-conferences", json={"text": "too short"}).status_code == 400
    assert client.post("/api/central-banks/BANXICO/press-conferences/fetch", json={}).status_code == 400
    assert client.delete(f"/api/central-banks/FED/press-conferences/{d['id']}").status_code == 200


def test_feed_pickup(client, db, monkeypatch):
    from app.db import utcnow
    from app.models import NewsArticle
    from app.services import pressers

    db.add(NewsArticle(uid="boc-os", title="Opening statement by Governor Macklem: Monetary Policy Report press conference",
                       url="https://example.org/boc-opening", source_name="Bank of Canada", feed="boc", kind="central_bank",
                       published_at=utcnow(), currencies=["CAD"], topics=[], tone="neutral"))
    db.add(NewsArticle(uid="boc-x", title="Bank of Canada publishes financial system review", url="https://example.org/x",
                       source_name="Bank of Canada", feed="boc", kind="central_bank", published_at=utcnow(), currencies=["CAD"],
                       topics=[], tone="neutral"))
    db.commit()

    class R:
        headers = {"content-type": "text/html"}
        content = ("<html><body><p>" + "Inflation remains elevated and we are prepared to raise rates further if needed. "
                   * 8 + "</p></body></html>").encode()

    monkeypatch.setattr(pressers, "http_get", lambda url, retries=1: R())
    r = client.post("/api/central-banks/BOC/press-conferences/fetch", json={})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["url"] == "https://example.org/boc-opening" and d["tone"] > 0
    lst = client.get("/api/central-banks/BOC/press-conferences").json()
    assert lst["auto"] is True and lst["full_transcript"] is False and len(lst["items"]) == 1
    # the scheduled job doesn't add it twice
    from app.ingestion.registry import run
    assert run(db, "pressers")["status"] == "OK"
    assert len(client.get("/api/central-banks/BOC/press-conferences").json()["items"]) == 1
    assert client.post("/api/central-banks/SARB/press-conferences/fetch", json={}).status_code == 400
