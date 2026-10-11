"""End-to-end API flows: manual input, review, confirmation, verification,
reconciliation, re-analysis, and every phase's endpoints."""
import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Alert, EconomicEvent, EconomicRelease, Indicator


def _commit_text(client, text, confirm=None, hint=None):
    sub = client.post("/api/manual/text", json={"text": text, "hint": hint}).json()
    r = client.post(f"/api/manual/{sub['id']}/confirm", json={"confirm": confirm} if confirm else {})
    assert r.status_code == 200, r.text
    return sub, r.json()


def test_typed_input_commits_unverified_and_reanalyses(client, db):
    sub, res = _commit_text(client, "US CPI September 2026 3.4% y/y, consensus 3.1%, previous 3.2%")
    assert sub["points"][0]["fields"]["indicator_code"] == "US_CPI_YOY"
    rel = db.get(EconomicRelease, res["committed"][0]["id"])
    assert rel.verification_status == "UNVERIFIED" and rel.input_method == "typed"
    msg = res["recompute_jobs"][0]["summary"]["message"]
    assert msg.startswith("Re-analysis complete.") and "Upside" in msg
    # data health shows it as awaiting verification
    h = client.get("/api/data-health").json()
    assert h["unverified"] == 1 and h["pending_verification"][0]["can_confirm"]


def test_user_confirmation_with_basis(client, db):
    _, res = _commit_text(client, "US CPI September 2026 3.4%, consensus 3.1%")
    rid = res["committed"][0]["id"]
    r = client.post(f"/api/data/{rid}/confirm", json={"basis": "SECONDARY_SOURCE"})
    assert r.status_code == 409  # secondary source must be named
    r = client.post(f"/api/data/{rid}/confirm", json={"basis": "OFFICIAL_SOURCE", "source_name": "BLS",
                                                      "source_url": "https://www.bls.gov/cpi/"}).json()
    assert r["status"] == "USER_CONFIRMED" and r["badge"] == "User-confirmed (official source: BLS)"
    assert "Re-analysis complete" in r["recompute"]["message"]
    audit = client.get(f"/api/data/{rid}/audit").json()
    assert any(a["action"] == "user_confirmed" for a in audit)
    assert client.post(f"/api/data/{rid}/unconfirm").json()["status"] == "UNVERIFIED"


def test_confirm_at_commit_time(client, db):
    _, res = _commit_text(client, "UK CPI August 2026 3.8%", confirm={"basis": "NO_SOURCE"})
    rel = db.get(EconomicRelease, res["committed"][0]["id"])
    assert rel.verification_status == "USER_CONFIRMED" and rel.confirmation_basis == "NO_SOURCE"


def test_background_verification_match_and_conflict(client, db):
    from app.services.verification_service import resolve_conflict, verify_pending

    _, a = _commit_text(client, "US CPI August 2026 3.3%")
    _, b = _commit_text(client, "US Unemployment Rate September 2026 4.3%", confirm={"basis": "OFFICIAL_SOURCE"})
    official = {"US_CPI_YOY": 3.3, "US_UNEMPLOYMENT": 4.4}
    stats = verify_pending(db, {"bls": lambda ind, period: official[ind.code]})
    assert stats["match"] == 1 and stats["mismatch"] == 1
    cpi = db.get(EconomicRelease, a["committed"][0]["id"])
    une = db.get(EconomicRelease, b["committed"][0]["id"])
    db.refresh(cpi)
    db.refresh(une)
    assert cpi.verification_status == "VERIFIED"
    assert une.verification_status == "CONFLICT"
    al = db.scalar(select(Alert).where(Alert.kind == "data_conflict"))
    assert al.severity == "HIGH"  # conflict with user-confirmed data
    recs = client.get("/api/reconciliation").json()
    assert recs[0]["manual_value"] == 4.3 and recs[0]["official_value"] == 4.4
    out = resolve_conflict(db, recs[0]["id"], "use_official")
    assert out["resolution"] == "use_official"
    ind = db.scalar(select(Indicator).where(Indicator.code == "US_UNEMPLOYMENT"))
    from app.services import data_access as da

    assert da.current_release(db, ind.id, "2026-09").actual == 4.4


def test_unreachable_source_keeps_value_unverified(client, db):
    from app.services.verification_service import verify_pending

    _, a = _commit_text(client, "US CPI July 2026 3.1%")

    def down(ind, period):
        raise ConnectionError("BLS unreachable")

    assert verify_pending(db, {"bls": down})["unreachable"] == 1
    rid = a["committed"][0]["id"]
    att = client.get(f"/api/data/{rid}/verification-attempts").json()
    assert att[0]["outcome"] == "unreachable"
    assert client.get(f"/api/data/{rid}").json()["verification_status"] == "UNVERIFIED"


def test_manual_value_conflicting_with_official_is_kept_separately(client, db):
    ind = db.scalar(select(Indicator).where(Indicator.code == "US_CPI_YOY"))
    ev = EconomicEvent(indicator_id=ind.id, reference_period="2026-06")
    db.add(ev)
    db.flush()
    db.add(EconomicRelease(event_id=ev.id, indicator_id=ind.id, reference_period="2026-06", actual=3.0,
                           input_method="automated", verification_status="VERIFIED"))
    db.commit()
    _, res = _commit_text(client, "US CPI June 2026 3.2%")
    assert "CONFLICT" in " ".join(res["committed"][0]["notes"])
    from app.services import data_access as da

    assert da.current_release(db, ind.id, "2026-06").actual == 3.0


def test_commit_blocked_on_errors_until_override(client, db):
    _commit_text(client, "US CPI May 2026 3.2%")
    sub = client.post("/api/manual/text", json={"text": "US CPI June 2026 32%, previous 3.2%"}).json()
    p = sub["points"][0]
    assert any(w["code"] == "DECIMAL_SHIFT" for w in p["warnings"]) and p["has_errors"]
    r = client.post(f"/api/manual/{sub['id']}/confirm", json={})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["needs"] == "override_reason"
    # fix it on the review screen instead
    fixed = client.patch(f"/api/manual/points/{p['id']}", json={"fields": {"actual": 3.2}}).json()
    assert not fixed["has_errors"] and fixed["field_confidence"]["actual"] == 100.0
    assert client.post(f"/api/manual/{sub['id']}/confirm", json={}).status_code == 200


def test_missing_fields_need_correction(client):
    sub = client.post("/api/manual/text", json={"text": "something 4.2"}).json()
    r = client.post(f"/api/manual/{sub['id']}/confirm", json={})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["needs"] == "correction"


def _png(text: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1400, 60 + 50 * text.count("\n")), "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    d.multiline_text((20, 20), text, fill="black", font=font, spacing=18)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_screenshot_upload_ocr_calendar(client, db):
    png = _png("Time Cur Event Actual Forecast Previous\n08:30 USD CPI y/y 3.4% 3.1% 3.2%\n"
               "08:30 USD Core CPI y/y 3.1% 3.0% 3.0%")
    r = client.post("/api/manual/upload", files={"file": ("calendar.png", png, "image/png")},
                    data={"hint": '{"reference_period": "2026-09"}'})
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub["input_method"] == "screenshot" and sub["files"][0]["sha256"]
    codes = {p["fields"].get("indicator_code"): p["fields"].get("actual") for p in sub["points"]}
    assert codes.get("US_CPI_YOY") == 3.4 and codes.get("US_CORE_CPI_YOY") == 3.1
    assert all(p["field_confidence"]["actual"] <= 100 for p in sub["points"])
    res = client.post(f"/api/manual/{sub['id']}/confirm", json={}).json()
    rel = db.get(EconomicRelease, res["committed"][0]["id"])
    assert rel.input_method == "screenshot" and rel.extraction_confidence is not None


def test_upload_rejects_disguised_executable(client):
    r = client.post("/api/manual/upload", files={"file": ("x.png", b"MZ\x90\x00binary", "image/png")})
    assert r.status_code == 415


def _pdf(lines: list[str]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for ln in lines:
        c.drawString(50, y, ln)
        y -= 20
    c.save()
    return buf.getvalue()


def test_pdf_projections_vintages_and_forecast_error(client, db):
    pdf = _pdf(["Federal Reserve Summary of Economic Projections, June 17, 2026",
                "Variable 2026 2027 2028 Longer run", "Change in real GDP 1.8 1.8 1.8 1.8",
                "Unemployment rate 4.4 4.3 4.2 4.2", "PCE inflation 2.6 2.2 2.0 2.0",
                "Core PCE inflation 2.8 2.3 2.0"])
    sub = client.post("/api/manual/upload", files={"file": ("sep.pdf", pdf, "application/pdf")}).json()
    assert sub["content_type"] == "cb_projections" and sub["input_method"] == "pdf"
    assert {p["fields"]["central_bank_code"] for p in sub["points"]} == {"FED"}
    assert sub["points"][0]["fields"]["vintage_date"] == "2026-06-17"
    client.post(f"/api/manual/{sub['id']}/confirm", json={})
    # second vintage via JSON API
    r = client.post("/api/central-banks/FED/projections", json={
        "vintage_date": "2026-09-16", "projections": [
            {"variable": "gdp", "target_period": "2026", "value": 1.4},
            {"variable": "core_inflation", "target_period": "2026", "value": 3.0},
            {"variable": "unemployment", "target_period": "2026", "value": 4.5}]}).json()
    assert "Re-analysis complete" in r["recompute"]["message"]
    proj = client.get("/api/central-banks/FED/projections").json()
    assert len(proj["vintages"]) == 2  # never overwritten
    gdp_rev = next(x for x in proj["revisions"] if x["variable"] == "gdp" and x["target_period"] == "2026")
    assert gdp_rev["momentum"] == "NEGATIVE"
    # release after the September vintage -> compared with what the Fed knew at the time
    _, res = _commit_text(client, "US Core PCE September 2026 3.4% y/y, consensus 3.1%",
                          hint={"release_date": "2026-10-01"})
    rep = client.get(f"/api/economic-releases/{res['committed'][0]['id']}/report").json()
    assert rep["central_bank_projection"] == 3.0
    assert rep["three_way"]["cb_error"] == 0.4 and rep["three_way"]["more_accurate"] == "market"
    assert rep["why_forecast_missed"]["method"] == "evidence_only"
    wa = client.get("/api/central-banks/FED/where-are-we").json()
    assert wa["table"][0]["classification"] == "Significantly Above Projection"
    acc = client.get("/api/central-banks/FED/forecast-accuracy?variable=core_inflation").json()
    assert acc["central_bank"]["core_inflation"]["n"] == 1


def test_statement_comparison_api(client):
    from tests.test_analytics import NEW, PREV

    client.post("/api/central-banks/FED/statements", json={"text": PREV, "published_date": "2026-07-29"})
    r = client.post("/api/central-banks/FED/statements", json={"text": NEW, "published_date": "2026-09-16"}).json()
    assert "Fed statement" in r["recompute"]["message"]
    cmp = client.get("/api/central-banks/FED/statement-comparison").json()
    assert cmp["summary"]["direction"] == "Dovish" and cmp["changes"]
    alerts = client.get("/api/alerts?kind=statement_change").json()["alerts"]
    assert alerts


def _seed_two_sides(client):
    for t in ("US CPI September 2026 3.4%, consensus 3.1%", "US Unemployment Rate September 2026 4.1%",
              "Euro area HICP September 2026 1.8%, consensus 2.0%", "EUR Unemployment Rate September 2026 6.4%"):
        _commit_text(client, t, confirm={"basis": "OFFICIAL_SOURCE"})
    client.post("/api/yields", json=[{"country": "US", "tenor": "2Y", "yield_pct": 4.4},
                                     {"country": "DE", "tenor": "2Y", "yield_pct": 2.1}])
    client.post("/api/rates/expectations", json={"central_bank_code": "FED", "prob_cut": 15, "prob_hold": 70,
                                                 "prob_hike": 15, "implied_12m_change_bps": 0})
    client.post("/api/rates/expectations", json={"central_bank_code": "ECB", "prob_cut": 60, "prob_hold": 40,
                                                 "prob_hike": 0, "implied_12m_change_bps": -75})
    client.post("/api/central-banks/FED/meetings", json={"meeting_date": "2026-09-16", "decision": "HOLD",
                                                         "rate_before": 4.5, "rate_after": 4.5})
    client.post("/api/central-banks/ECB/meetings", json={"meeting_date": "2026-09-10", "decision": "CUT",
                                                         "rate_before": 2.25, "rate_after": 2.0})


def test_full_pipeline_fundamental_and_no_trade(client, db):
    _seed_two_sides(client)
    job = client.post("/api/recompute/full").json()
    assert job["status"] == "done" and not job["summary"]["failed"], job["summary"]
    a = client.get("/api/fundamental/EURUSD").json()
    assert a["bias"] in ("BEARISH", "NEUTRAL") and a["confluence_total"] < 0
    assert a["data_status"] == "Relies on user-confirmed data"
    assert a["report"]["conclusion"] and a["disclaimer"]
    assert isinstance(a["no_trade_reasons"], list)
    # an imminent high-importance release forces NO TRADE
    ind = db.scalar(select(Indicator).where(Indicator.code == "US_NFP"))
    db.add(EconomicEvent(indicator_id=ind.id, reference_period="2026-09",
                         scheduled_at=datetime.now(timezone.utc) + timedelta(hours=3)))
    db.commit()
    a2 = client.get("/api/fundamental/EURUSD").json()
    assert a2["grade"] == "NO TRADE" and any("pending" in r for r in a2["no_trade_reasons"])
    sc = client.get("/api/scenarios/EURUSD").json()
    assert sum(s["probability"] for s in sc["scenarios"]) == 100 and len(sc["scenarios"]) == 4
    dash = client.get("/api/dashboard").json()
    assert dash["regime"] and dash["central_bank_heatmap"] and dash["ai_summary"]
    cur = client.get("/api/currencies").json()
    assert cur["heatmap"]["matrix"]["USD"]["EUR"]["symbol"] in ("+", "++", "=")
    div = client.get("/api/policy-divergence").json()
    assert any(d["pair"] == "FED/ECB" for d in div)
    cal = client.get("/api/economic-calendar").json()
    assert any(e["indicator"] == "US_NFP" and e["data_status"] == "SCHEDULED" for e in cal)


def test_ai_search_intents(client):
    _seed_two_sides(client)
    client.post("/api/recompute/full")
    for q, intent in (("Why is EUR/USD bearish?", "asset_analysis"), ("Is the Fed becoming more dovish?", "policy"),
                      ("Which currency has the strongest fundamentals?", "currency_ranking"),
                      ("Is the market underpricing inflation?", "market_wrong"),
                      ("What would make GBP/USD bullish?", "conditions"),
                      ("Which upcoming event has the highest potential market impact?", "catalysts"),
                      ("Did the Fed underestimate inflation?", "forecast_accuracy")):
        r = client.post("/api/ai/search", json={"question": q}).json()
        assert r["intent"] == intent, (q, r["intent"])
        assert r["conclusion"]
    r = client.post("/api/ai/search", json={"question": "Why is EUR/USD bearish?"}).json()
    assert r["citations"] and all("status" in c for c in r["citations"])


def test_missing_scheduled_release_prompts_manual_input(client, db):
    ind = db.scalar(select(Indicator).where(Indicator.code == "US_CPI_YOY"))
    db.add(EconomicEvent(indicator_id=ind.id, reference_period="2026-09",
                         scheduled_at=datetime.now(timezone.utc) - timedelta(hours=2)))
    db.commit()
    h = client.get("/api/data-health").json()
    assert h["missing_scheduled"] and "No actual value received" in h["missing_scheduled"][0]["message"]
    cal = client.get("/api/economic-calendar").json()
    assert any(e["needs_manual_input"] for e in cal)


def test_source_failure_tracked_and_alerted(client, db):
    from app.ingestion.base import run_source

    def boom(db_, src):
        raise RuntimeError("feed returned 503")

    res = run_source(db, "fed_rss", boom)
    assert res["status"] == "FAILED"
    h = client.get("/api/data-health").json()
    fed = next(s for s in h["sources"] if s["key"] == "fed_rss")
    assert fed["status"] == "FAILED" and fed["needs_manual_input"] and fed["retries"] == 1
    assert db.scalar(select(Alert).where(Alert.kind == "source_failure"))


def test_delete_upload_restores_previous(client, db):
    s1, r1 = _commit_text(client, "US CPI April 2026 3.0%")
    s2, r2 = _commit_text(client, "US CPI April 2026 3.1%")
    out = client.delete(f"/api/manual/{s2['id']}").json()
    assert out["releases_removed"] == 1
    old = db.get(EconomicRelease, r1["committed"][0]["id"])
    db.refresh(old)
    assert old.is_current and old.actual == 3.0


def test_trust_settings_auto_confirm(client, db):
    client.put("/api/settings/trust", json={"auto_confirm_typed": True})
    _, res = _commit_text(client, "US CPI March 2026 2.9%")
    rel = db.get(EconomicRelease, res["committed"][0]["id"])
    assert rel.verification_status == "USER_CONFIRMED" and rel.confirmation_basis == "NO_SOURCE"


def test_watchlist_and_graph(client):
    assert client.post("/api/watchlist", json={"asset": "USD/ZAR"}).json()["asset"] == "USDZAR"
    g = client.get("/api/recompute/graph").json()
    names = {n["node"] for n in g["nodes"]}
    assert {"surprise", "policy_score", "scenarios", "trade_setups", "market_wrong"} <= names
    assert "surprise" in g["triggers"]["release"]
