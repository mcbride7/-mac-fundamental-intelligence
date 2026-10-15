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
