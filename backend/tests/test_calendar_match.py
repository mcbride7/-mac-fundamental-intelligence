from datetime import datetime, timezone


def test_provider_actual_fills_the_event_on_the_calendar(db):
    """A release FMP labels "(Sep)" but the calendar filed as October (released in November) must still land on
    the calendar's event, matched by release time, not create a separate one."""
    from app.ingestion.markets import calendar_event
    from app.models import EconomicEvent
    from app.services import data_access as da

    ind = da.indicator_by_code(db, "GB_UNEMPLOYMENT")
    when = datetime(2026, 11, 11, 7, 0, tzinfo=timezone.utc)
    shown = EconomicEvent(indicator_id=ind.id, reference_period="2026-10", importance=ind.importance, scheduled_at=when)
    db.add(shown)
    db.commit()
    ev = calendar_event(db, ind, datetime(2026, 11, 11, 7, 0, tzinfo=timezone.utc), "Unemployment Rate (Sep)")
    assert ev.id == shown.id
    # weekly releases use the calendar's week convention when nothing is scheduled yet
    claims = da.indicator_by_code(db, "US_JOBLESS_CLAIMS")
    ev2 = calendar_event(db, claims, datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc), "Initial Jobless Claims (Nov/07)")
    assert ev2.reference_period == "2026-11-07"
