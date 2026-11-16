"""FMP lists every sub-measure next to the headline release. Only the headline may fill a site indicator."""
from datetime import date, datetime, timedelta, timezone

import pytest


def _item(event, country="US", unit="%", actual=1.0, estimate=None, when="2026-11-10 13:30:00"):
    return {"date": when, "country": country, "event": event, "unit": unit, "actual": actual,
            "estimate": estimate, "previous": None, "impact": "High"}


@pytest.fixture()
def match(db):
    from sqlalchemy import select

    from app.ingestion.markets import fmp_match, fmp_refs
    from app.models import Indicator
    from app.services import data_access as da

    refs = fmp_refs(da.indicator_refs(db))
    freq = dict(db.execute(select(Indicator.code, Indicator.frequency)).all())
    cmap = {"EU": "EA", "UK": "GB"}
    return lambda it: fmp_match(it, cmap.get(it["country"], it["country"]), refs, freq)


@pytest.mark.parametrize("event,country,unit,code", [
    ("Inflation Rate YoY (Oct)", "US", "%", "US_CPI_YOY"),
    ("Inflation Rate MoM (Oct)", "US", "%", "US_CPI_MOM"),
    ("Core Inflation Rate YoY (Oct)", "US", "%", "US_CORE_CPI_YOY"),
    ("Non Farm Payrolls (Oct)", "US", "K", "US_NFP"),
    ("Unemployment Rate (Oct)", "US", "%", "US_UNEMPLOYMENT"),
    ("ISM Manufacturing PMI (Oct)", "US", None, "US_ISM_MANUF"),
    ("S&P Global Manufacturing PMI (Oct)", "US", "Points", "US_SPG_MANUF_PMI"),
    ("Michigan Consumer Sentiment (Nov)", "US", None, "US_UMICH"),
    ("Initial Jobless Claims (Nov/07)", "US", "K", "US_JOBLESS_CLAIMS"),
    ("Inflation Rate YoY (Oct)", "EU", "%", "EA_HICP_YOY"),
    ("Deposit Facility Rate (Oct)", "EU", "%", "EA_ECB_RATE"),
    ("S&P Global Composite PMI (Oct)", "EU", "Points", "EA_PMI_COMPOSITE"),
    ("GDP Growth Rate QoQ (Q3)", "UK", "%", "GB_GDP_QOQ"),
    ("GDP Growth Rate QoQ (Q3)", "JP", "%", "JP_GDP_QOQ"),
    ("Gross Domestic Product MoM (Sep)", "CA", "%", "CA_GDP_MOM"),
    ("Business NZ PMI (Oct)", "NZ", None, "NZ_MANUF_PMI"),
    ("Westpac Consumer Confidence Index (Nov)", "AU", None, "AU_CONSUMER_CONF"),
    ("NBS Non Manufacturing PMI (Oct)", "CN", None, "CN_SERVICES_PMI"),
    ("NBS Manufacturing PMI (Oct)", "CN", None, "CN_MANUF_PMI"),
    ("Inflation Rate YoY (Q3)", "AU", "%", "AU_CPI_YOY"),
])
def test_headline_releases_match(match, event, country, unit, code):
    assert match(_item(event, country, unit)) == code


@pytest.mark.parametrize("event,country,unit", [
    ("ISM Manufacturing Prices (Oct)", "US", None),
    ("ISM Manufacturing Employment (Oct)", "US", None),
    ("Government Payrolls (Oct)", "US", "K"),
    ("Manufacturing Payrolls (Oct)", "US", "K"),
    ("U-6 Unemployment Rate (Oct)", "US", "%"),
    ("Michigan 1 Year Inflation Expectations (Nov)", "US", "%"),
    ("Consumer Inflation Expectation (Oct)", "US", "%"),
    ("CPI (Oct)", "US", "Index"),            # index level, not y/y
    ("CPI s.a (Oct)", "US", None),
    ("Producer Price Index (Oct)", "US", None),
    ("Continuing Jobless Claims (Oct/31)", "US", "K"),
    ("JOLTs Job Quits (Sep)", "US", "M"),
    ("GDP Price Index QoQ (Q3)", "US", "%"),
    ("GDP Capital Expenditure QoQ (Q3)", "JP", "%"),
    ("GDP Growth Annualized (Q3)", "JP", "%"),
    ("Tokyo CPI YoY (Oct)", "JP", "%"),        # Tokyo is not the national CPI
    ("CPI (Oct)", "EU", "Index"),
    ("Median CPI YoY (Sep)", "AU", "%"),
    ("Inflation Rate YoY (Sep)", "AU", "%"),   # monthly print vs the quarterly indicator
    ("RBA Trimmed Mean CPI YoY (Q3)", "AU", "%"),  # quarterly print vs the monthly indicator
    ("Westpac Consumer Confidence Change (Nov)", "AU", "%"),
    ("Gross Domestic Product YoY (Sep)", "UK", "%"),  # monthly GDP vs quarterly GDP y/y
    ("Unemployment Rate n.s.a (Oct)", "CH", "%"),
])
def test_sub_measures_never_fill_a_headline(match, event, country, unit):
    assert match(_item(event, country, unit)) is None


def test_run_fmp_keeps_headline_and_removes_old_wrong_matches(db, monkeypatch):
    """The ISM PMI arrives with its sub-indices: only the PMI is stored. A wrong figure left by the old
    loose matching (ISM Prices filed as the ISM PMI) is replaced, and a bogus period it created is removed."""
    from app.config import settings
    from app.ingestion import markets
    from app.ingestion.fred import upsert_official_release
    from app.models import EconomicEvent, Source
    from app.services import data_access as da
    from sqlalchemy import select

    src = db.scalar(select(Source).where(Source.key == "fmp"))
    ism = da.indicator_by_code(db, "US_ISM_MANUF")
    cpi = da.indicator_by_code(db, "US_CPI_YOY")
    t = datetime.now(timezone.utc) - timedelta(days=3)
    period = f"{t.year}-{t.month:02d}"
    # what the old matching left behind
    upsert_official_release(db, src, ism, period, 75.2, None, t)            # ISM Prices as the PMI
    upsert_official_release(db, src, cpi, "2099-01", 4.3, None, t)          # Michigan expectations as CPI
    db.commit()

    when = t.strftime("%Y-%m-%d %H:%M:%S")
    first = (date.today() - timedelta(days=markets.FMP_LOOKBACK_DAYS)).isoformat() + " 00:00:00"
    filler = [_item("Some Auction", "US", "%", 1.0, when=first) for _ in range(120)]
    rows = [_item("ISM Manufacturing Prices", "US", None, 75.2, when=when),
            _item("ISM Manufacturing PMI", "US", None, 55.5, when=when),
            _item("ISM Manufacturing Employment", "US", None, 52.4, when=when)] + filler
    monkeypatch.setattr(settings, "fmp_api_key", "x")
    monkeypatch.setattr(markets, "_fmp_get", lambda params: rows)
    markets.run_fmp(db, src)

    rel = da.latest_current(db, ism.id)
    assert rel.actual == 55.5
    assert da.current_release(db, cpi.id, "2099-01") is None
    assert da.event_for(db, cpi.id, "2099-01") is None
    assert db.scalar(select(EconomicEvent).where(EconomicEvent.indicator_id == ism.id)) is not None
