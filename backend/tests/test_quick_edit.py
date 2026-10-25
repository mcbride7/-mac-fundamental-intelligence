from datetime import datetime, timezone


def _event(db, code="US_CPI_YOY", period="2026-09", consensus=3.0, previous=2.9):
    from app.models import EconomicEvent
    from app.services import data_access as da

    ind = da.indicator_by_code(db, code)
    ev = EconomicEvent(indicator_id=ind.id, reference_period=period, importance="high", consensus=consensus,
                       previous=previous, scheduled_at=datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc))
    db.add(ev)
    db.commit()
    return ev, ind


def test_edit_forecast_and_previous(client, db):
    ev, _ = _event(db)
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "consensus", "value": 3.2})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "previous", "value": 3.0})
    assert r.status_code == 200
    db.refresh(ev)
    assert ev.consensus == 3.2 and ev.consensus_source == "manual" and ev.previous == 3.0


def test_edit_actual_goes_through_checks(client, db):
    from app.services import data_access as da

    ev, ind = _event(db)
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "actual", "value": 3.1})
    assert r.status_code == 200, r.text
    rel = da.current_release(db, ind.id, "2026-09")
    assert rel.actual == 3.1 and rel.verification_status == "UNVERIFIED" and rel.input_method == "typed"
    # a correction becomes a new revision; the old value is kept
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "actual", "value": 3.15})
    assert r.status_code == 200, r.text
    assert da.current_release(db, ind.id, "2026-09").actual == 3.15


def test_suspicious_actual_needs_a_reason(client, db):
    ev, _ = _event(db)
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "actual", "value": 31})
    assert r.status_code == 422
    assert r.json()["detail"]["problems"][0]["needs"] == "override_reason"
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "actual", "value": 31, "reason": "checked BLS"})
    assert r.status_code == 200, r.text


def test_bad_field_rejected(client, db):
    ev, _ = _event(db)
    assert client.patch(f"/api/economic-events/{ev.id}", json={"field": "importance", "value": 1}).status_code == 400
    assert client.patch("/api/economic-events/999999", json={"field": "actual", "value": 1}).status_code == 404


def _row(client, ev_id):
    rows = client.get("/api/economic-calendar?start=2026-10-01&end=2026-10-31").json()
    return next(r for r in rows if r["event_id"] == ev_id)


def test_edit_cb_projection_adds_a_vintage(client, db):
    from app.models import ProjectionVintage

    ev, ind = _event(db, code="US_PCE_YOY", consensus=2.8, previous=2.7)
    assert ind.projection_variable and ind.central_bank_code
    assert client.patch(f"/api/economic-events/{ev.id}", json={"field": "actual", "value": 2.9}).status_code == 200
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "cb_projection", "value": 2.6})
    assert r.status_code == 200, r.text
    row = _row(client, ev.id)
    assert row["central_bank_projection"] == 2.6 and row["projection_editable"]
    v = db.get(ProjectionVintage, r.json()["vintage_id"])
    assert str(v.vintage_date) == "2026-10-13" and v.input_method == "typed"  # day before the release
    # a second edit is a new round; the newest one counts
    assert client.patch(f"/api/economic-events/{ev.id}", json={"field": "cb_projection", "value": 2.7}).status_code == 200
    assert _row(client, ev.id)["central_bank_projection"] == 2.7
    assert client.patch(f"/api/economic-events/{ev.id}", json={"field": "cb_projection", "value": None}).status_code == 400


def test_edit_surprise_override_and_clear(client, db):
    ev, _ = _event(db)
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "surprise", "value": 0.3})
    assert r.status_code == 400  # no actual yet
    assert client.patch(f"/api/economic-events/{ev.id}", json={"field": "actual", "value": 3.1}).status_code == 200
    row = _row(client, ev.id)
    assert abs(row["surprise"] - 0.1) < 1e-9 and not row["surprise_edited"]
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "surprise", "value": 0.4, "reason": "vs my forecast"})
    assert r.status_code == 200, r.text
    row = _row(client, ev.id)
    assert abs(row["surprise"] - 0.4) < 1e-9 and row["surprise_edited"] and abs(row["surprise_calculated"] - 0.1) < 1e-9
    assert row["surprise_reason"] == "vs my forecast"
    # clearing goes back to actual - forecast
    assert client.patch(f"/api/economic-events/{ev.id}", json={"field": "surprise", "value": None}).status_code == 200
    row = _row(client, ev.id)
    assert abs(row["surprise"] - 0.1) < 1e-9 and not row["surprise_edited"]


def test_projection_not_offered_where_no_bank_projects(client, db):
    ev, _ = _event(db)  # US CPI: the Fed projects PCE, not CPI
    r = client.patch(f"/api/economic-events/{ev.id}", json={"field": "cb_projection", "value": 2.6})
    assert r.status_code == 400 and "No central bank" in r.json()["detail"]
    assert _row(client, ev.id)["projection_editable"] is False
