from datetime import datetime, timezone

from app.ingestion.forexfactory import parse_value, reference_period, store


def test_parse_value():
    assert parse_value("3.1%", "%") == 3.1
    assert parse_value("-0.2%", "%") == -0.2
    assert parse_value("<0.1%", "%") == 0.1
    assert parse_value("250K", "k") == 250
    assert parse_value("1.2M", "k") == 1200
    assert parse_value("52.3", "index") == 52.3
    assert parse_value("", "%") is None and parse_value(None, "%") is None


def test_reference_period():
    oct14 = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    assert reference_period("monthly", oct14, "CPI y/y") == "2026-09"
    assert reference_period("quarterly", oct14, "Advance GDP q/q") == "2026Q3"
    assert reference_period("quarterly", datetime(2026, 12, 20, tzinfo=timezone.utc), "Final GDP q/q") == "2026Q3"
    assert reference_period("quarterly", datetime(2027, 1, 29, tzinfo=timezone.utc), "Advance GDP q/q") == "2026Q4"
    assert reference_period("meeting", datetime(2026, 10, 28, tzinfo=timezone.utc), "Federal Funds Rate") == "2026-10"
    assert reference_period("monthly", datetime(2026, 10, 31, tzinfo=timezone.utc), "CPI Flash Estimate y/y") == "2026-10"


def test_store_fills_calendar(db):
    from app.services import data_access as da

    items = [
        {"title": "CPI y/y", "country": "USD", "date": "2026-10-14T08:30:00-04:00", "impact": "High",
         "forecast": "3.1%", "previous": "2.9%"},
        {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-11-06T08:30:00-05:00",
         "impact": "High", "forecast": "150K", "previous": "254K"},
        {"title": "CPI y/y", "country": "GBP", "date": "2026-10-15T07:00:00+01:00", "impact": "High",
         "forecast": "3.7%", "previous": "3.8%"},
        {"title": "German Prelim CPI m/m", "country": "EUR", "date": "2026-10-30T09:00:00+01:00", "impact": "High",
         "forecast": "0.2%", "previous": "0.1%"},
        {"title": "Bank Holiday", "country": "JPY", "date": "2026-10-13T00:00:00+09:00", "impact": "Holiday",
         "forecast": "", "previous": ""},
    ]
    n, seen = store(db, items)
    assert (n, seen) == (3, 5)
    us = da.event_for(db, da.indicator_by_code(db, "US_CPI_YOY").id, "2026-09")
    assert us.consensus == 3.1 and us.previous == 2.9 and us.consensus_source == "forexfactory"
    assert us.scheduled_at.hour == 12  # 08:30 New York = 12:30 UTC
    nfp = da.event_for(db, da.indicator_by_code(db, "US_NFP").id, "2026-10")
    assert nfp.consensus == 150 and nfp.previous == 254
    # a forecast typed in by hand is kept
    us.consensus, us.consensus_source = 3.0, "manual"
    db.commit()
    store(db, items)
    assert da.event_for(db, da.indicator_by_code(db, "US_CPI_YOY").id, "2026-09").consensus == 3.0


def test_forexfactory_is_a_runnable_source(client):
    srcs = {s["key"] for s in client.get("/api/sources").json()}
    assert "forexfactory" in srcs
