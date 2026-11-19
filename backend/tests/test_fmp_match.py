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


def test_calendar_figure_wins_over_other_sources(db):
    """The economic calendar comes first: FRED / OECD printing the same period with other rounding never
    replaces it, the calendar replaces theirs, and they still fill a period the calendar hasn't got."""
    from sqlalchemy import select

    from app.ingestion.fred import upsert_official_release
    from app.models import Source
    from app.services import data_access as da

    fmp = db.scalar(select(Source).where(Source.key == "fmp"))
    other = db.scalar(select(Source).where(Source.key.notin_(["fmp", "finnhub", "forexfactory", "manual"])))
    gdp = da.indicator_by_code(db, "JP_GDP_YOY")
    when = datetime(2026, 11, 15, 23, 50, tzinfo=timezone.utc)

    upsert_official_release(db, fmp, gdp, "2026Q3", -0.1, 0.3, when)
    db.flush()
    assert upsert_official_release(db, other, gdp, "2026Q3", -0.06, None, when) == 0   # can't replace it
    db.commit()
    assert da.latest_current(db, gdp.id).actual == -0.1

    upsert_official_release(db, other, gdp, "2026Q2", 1.6, None, when)                # other source first
    db.flush()
    upsert_official_release(db, fmp, gdp, "2026Q2", 1.7, None, when)                  # calendar replaces it
    db.commit()
    assert da.current_release(db, gdp.id, "2026Q2").actual == 1.7

    upsert_official_release(db, other, gdp, "2026Q4", 0.5, None, when)                # calendar hasn't got it yet
    db.commit()
    assert da.latest_current(db, gdp.id).actual == 0.5


@pytest.mark.parametrize("freq,when,name,period", [
    ("monthly", datetime(2026, 10, 29, 5, tzinfo=timezone.utc), "Consumer Confidence (Oct)", "2026-10"),
    ("monthly", datetime(2026, 11, 5, 0, 30, tzinfo=timezone.utc), "S&P Global Services PMI (Oct)", "2026-10"),
    ("monthly", datetime(2027, 1, 12, 7, tzinfo=timezone.utc), "Inflation Rate YoY (Dec)", "2026-12"),
    ("quarterly", datetime(2026, 11, 15, 23, 50, tzinfo=timezone.utc), "GDP Growth Rate QoQ (Q3)", "2026Q3"),
    ("quarterly", datetime(2027, 2, 15, 23, 50, tzinfo=timezone.utc), "GDP Growth Rate QoQ (Q4)", "2026Q4"),
    ("weekly", datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc), "Initial Jobless Claims (Nov/07)", None),
    ("monthly", datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc), "Non Farm Payrolls", None),
])
def test_period_comes_from_fmp_tag(freq, when, name, period):
    from app.ingestion.markets import tagged_period

    assert tagged_period(freq, when, name) == period


def test_fmp_files_release_under_its_printed_period(db, monkeypatch):
    """Japan's October consumer confidence comes out on 29 October. The release-date rule filed the calendar
    event as September; FMP's "(Oct)" moves it to October and the figure is stored there."""
    from sqlalchemy import select

    from app.config import settings
    from app.ingestion import markets
    from app.models import EconomicEvent, Source
    from app.services import data_access as da

    src = db.scalar(select(Source).where(Source.key == "fmp"))
    ind = da.indicator_by_code(db, "JP_CONSUMER_CONF")
    t = datetime.now(timezone.utc).replace(hour=5, minute=0, second=0, microsecond=0) - timedelta(days=2)
    prev = (t.replace(day=1) - timedelta(days=1))
    wrong, right = f"{prev.year}-{prev.month:02d}", f"{t.year}-{t.month:02d}"
    db.add(EconomicEvent(indicator_id=ind.id, reference_period=wrong, importance="high", scheduled_at=t))
    db.commit()

    mon = t.strftime("%b")
    when = t.strftime("%Y-%m-%d %H:%M:%S")
    first = (date.today() - timedelta(days=markets.FMP_LOOKBACK_DAYS)).isoformat() + " 00:00:00"
    rows = [_item(f"Consumer Confidence ({mon})", "JP", "%", 35.0, 35.1, when=when)] + \
        [_item("Some Auction", "US", "%", 1.0, when=first) for _ in range(120)]
    monkeypatch.setattr(settings, "fmp_api_key", "x")
    monkeypatch.setattr(markets, "_fmp_get", lambda params: rows)
    markets.run_fmp(db, src)

    rel = da.latest_current(db, ind.id)
    assert rel.reference_period == right and rel.actual == 35.0
    assert da.event_for(db, ind.id, wrong) is None
    assert db.scalars(select(EconomicEvent).where(EconomicEvent.indicator_id == ind.id)).all() == \
        [da.event_for(db, ind.id, right)]


def test_finnhub_stands_down_when_fmp_is_set(db, monkeypatch):
    from sqlalchemy import select

    from app.config import settings
    from app.ingestion import markets
    from app.models import Source

    monkeypatch.setattr(settings, "fmp_api_key", "x")
    src = db.scalar(select(Source).where(Source.key == "finnhub"))
    assert markets.run_finnhub(db, src) == 0


def _typed(db, ind, period, value, made):
    """A number typed in on the Macro page the old way (period = the month it was typed in)."""
    from app.models import EconomicEvent, EconomicRelease

    ev = EconomicEvent(indicator_id=ind.id, reference_period=period, importance="low", scheduled_at=made)
    db.add(ev)
    db.flush()
    rel = EconomicRelease(event_id=ev.id, indicator_id=ind.id, reference_period=period, actual=value,
                          unit=ind.unit, released_at=made, revision_number=0, source_name="manual",
                          input_method="typed", verification_status="UNVERIFIED", created_at=made)
    db.add(rel)
    db.flush()
    return rel


def test_typed_number_filed_under_typing_month_is_moved(db):
    """UK PPI input 8.3% typed on 2 Nov was filed as 2026-11 and hid the calendar's October 10.8%.
    It is September's figure (October's came out on 18 Nov): it moves there and October shows."""
    from app.ingestion.fred import upsert_official_release
    from app.models import EconomicEvent, Source
    from app.services import data_access as da
    from app.services.macro_edit import fix_too_new_periods
    from sqlalchemy import select

    fmp = db.scalar(select(Source).where(Source.key == "fmp"))
    ind = da.indicator_by_code(db, "GB_PPI_YOY")
    db.add(EconomicEvent(indicator_id=ind.id, reference_period="2026-09", importance="low",
                         scheduled_at=datetime(2026, 10, 15, 6, tzinfo=timezone.utc)))
    db.flush()
    upsert_official_release(db, fmp, ind, "2026-10", 10.8, 9.1, datetime(2026, 11, 18, 7, tzinfo=timezone.utc))
    ev10 = da.event_for(db, ind.id, "2026-10")
    ev10.scheduled_at = datetime(2026, 11, 18, 7, tzinfo=timezone.utc)
    typed = _typed(db, ind, "2026-11", 8.3, datetime(2026, 11, 2, 9, tzinfo=timezone.utc))
    db.commit()
    assert da.latest_current(db, ind.id).actual == 8.3   # the bug

    assert fix_too_new_periods(db) == 1
    assert da.latest_current(db, ind.id).actual == 10.8
    assert da.current_release(db, ind.id, "2026-09").id == typed.id
    assert da.event_for(db, ind.id, "2026-11") is None
    assert fix_too_new_periods(db) == 0                    # nothing left to move


def test_typed_number_where_calendar_has_the_period_is_retired(db):
    """UK GDP y/y typed on 2 Nov became 2026Q4; the calendar already holds Q2 (the latest out then)."""
    from app.ingestion.fred import upsert_official_release
    from app.models import Source
    from app.services import data_access as da
    from app.services.macro_edit import fix_too_new_periods
    from sqlalchemy import select

    fmp = db.scalar(select(Source).where(Source.key == "fmp"))
    ind = da.indicator_by_code(db, "GB_GDP_YOY")
    upsert_official_release(db, fmp, ind, "2026Q2", 1.4, None, datetime(2026, 8, 14, 6, tzinfo=timezone.utc))
    da.event_for(db, ind.id, "2026Q2").scheduled_at = datetime(2026, 8, 14, 6, tzinfo=timezone.utc)
    upsert_official_release(db, fmp, ind, "2026Q3", 1.9, 1.9, datetime(2026, 11, 12, 7, tzinfo=timezone.utc))
    da.event_for(db, ind.id, "2026Q3").scheduled_at = datetime(2026, 11, 12, 7, tzinfo=timezone.utc)
    typed = _typed(db, ind, "2026Q4", 1.4, datetime(2026, 11, 2, 9, tzinfo=timezone.utc))
    db.commit()

    fix_too_new_periods(db)
    assert da.latest_current(db, ind.id).actual == 1.9
    db.refresh(typed)
    assert typed.is_current is False and typed.reference_period == "2026Q2"
    assert da.event_for(db, ind.id, "2026Q4") is None


def test_add_box_suggests_the_last_published_period(db, monkeypatch):
    from app.services import data_access as da
    from app.services import macro_edit
    from app.models import EconomicEvent

    ind = da.indicator_by_code(db, "GB_PPI_YOY")
    db.add(EconomicEvent(indicator_id=ind.id, reference_period="2026-09", importance="low",
                         scheduled_at=datetime(2026, 10, 15, 6, tzinfo=timezone.utc)))
    db.add(EconomicEvent(indicator_id=ind.id, reference_period="2026-10", importance="low",
                         scheduled_at=datetime(2026, 11, 18, 7, tzinfo=timezone.utc)))
    db.commit()
    monkeypatch.setattr(macro_edit, "utcnow", lambda: datetime(2026, 11, 2, 9, tzinfo=timezone.utc))
    assert macro_edit.default_period(ind, db) == "2026-09"
    monkeypatch.setattr(macro_edit, "utcnow", lambda: datetime(2026, 11, 20, 9, tzinfo=timezone.utc))
    assert macro_edit.default_period(ind, db) == "2026-10"


@pytest.mark.parametrize("event,country,code", [
    ("Interest Rate Decision (Nov)", "AU", "AU_RBA_RATE"),
    ("BoC Interest Rate Decision", "CA", "CA_BOC_RATE"),
    ("SNB Interest Rate Decision", "CH", "CH_SNB_RATE"),
    ("RBNZ Interest Rate Decision", "NZ", "NZ_RBNZ_RATE"),
    ("Interest Rate Decision (Nov)", "MX", "MX_BANXICO_RATE"),
    ("Loan Prime Rate 1Y", "CN", "CN_LPR_1Y"),
    ("Fed Interest Rate Decision", "US", "US_FED_RATE"),
    ("BoE Interest Rate Decision", "UK", "GB_BOE_RATE"),
    ("Consumer Confidence (Oct)", "UK", "GB_CONSUMER_CONF"),
    ("Consumer Confidence (Oct)", "CH", "CH_CONSUMER_CONF"),
])
def test_every_central_bank_rate_matches(match, event, country, code):
    assert match(_item(event, country, "%")) == code


def test_calendar_replaces_an_unconfirmed_typed_number(db):
    """Calendar first: FMP's figure replaces a typed-in number nobody confirmed (no 'conflict' left
    showing the typed one)."""
    from sqlalchemy import select

    from app.ingestion.fred import upsert_official_release
    from app.models import Source
    from app.services import data_access as da

    fmp = db.scalar(select(Source).where(Source.key == "fmp"))
    ind = da.indicator_by_code(db, "GB_PPI_YOY")
    typed = _typed(db, ind, "2026-10", 9.0, datetime(2026, 11, 17, 9, tzinfo=timezone.utc))
    db.commit()
    upsert_official_release(db, fmp, ind, "2026-10", 10.8, 9.1, datetime(2026, 11, 18, 7, tzinfo=timezone.utc))
    db.commit()
    rel = da.latest_current(db, ind.id)
    assert rel.actual == 10.8 and rel.input_method == "automated"
    db.refresh(typed)
    assert typed.is_current is False


def test_only_one_decision_stored_uses_calendar_previous(db):
    """Banxico cut 6.50 -> 6.25: with one decision stored, FMP's previous rate shows it was a cut."""
    from sqlalchemy import select

    from app.engines import fundamentals as fnd
    from app.ingestion import markets
    from app.models import Source

    src = db.scalar(select(Source).where(Source.key == "fmp"))
    when = datetime.now(timezone.utc) - timedelta(days=3)
    first = (date.today() - timedelta(days=markets.FMP_LOOKBACK_DAYS)).isoformat() + " 00:00:00"
    item = _item("Interest Rate Decision", "MX", "%", 6.25, 6.5, when=when.strftime("%Y-%m-%d %H:%M:%S"))
    item["previous"] = 6.5
    rows = [item] + [_item("Some Auction", "US", "%", 1.0, when=first) for _ in range(120)]
    import app.config as cfg
    old = cfg.settings.fmp_api_key
    cfg.settings.fmp_api_key = "x"
    try:
        markets._fmp_get, keep = (lambda params: rows), markets._fmp_get
        markets.run_fmp(db, src)
    finally:
        markets._fmp_get = keep
        cfg.settings.fmp_api_key = old
    snap = fnd.build(db, "MXN")
    assert snap.policy_rate == 6.25 and snap.last_decision == "CUT" and snap.last_change_bps == -25


def _fmp_at(db, code, period, value, when):
    from sqlalchemy import select

    from app.ingestion.fred import upsert_official_release
    from app.models import Source
    from app.services import data_access as da

    fmp = db.scalar(select(Source).where(Source.key == "fmp"))
    ind = da.indicator_by_code(db, code)
    upsert_official_release(db, fmp, ind, period, value, None, when)
    da.event_for(db, ind.id, period).scheduled_at = when
    db.flush()
    return ind


def test_typed_future_period_is_retired_even_if_confirmed(db):
    """ISM services typed on 1 Nov as '2026-12' (confirmed): that period hadn't started. October's FMP figure shows."""
    from app.services import data_access as da
    from app.services.macro_edit import fix_too_new_periods

    ind = _fmp_at(db, "US_ISM_SERVICES", "2026-09", 53.8, datetime(2026, 10, 6, 14, tzinfo=timezone.utc))
    _fmp_at(db, "US_ISM_SERVICES", "2026-10", 54.5, datetime(2026, 11, 4, 15, tzinfo=timezone.utc))
    typed = _typed(db, ind, "2026-12", 54.9, datetime(2026, 11, 1, 9, tzinfo=timezone.utc))
    typed.verification_status = "USER_CONFIRMED"
    db.commit()
    assert da.latest_current(db, ind.id).actual == 54.9      # the bug
    fix_too_new_periods(db)
    assert da.latest_current(db, ind.id).actual == 54.5
    db.refresh(typed)
    assert typed.reference_period == "2026-09" and typed.is_current is False
    assert da.event_for(db, ind.id, "2026-12") is None


def test_typed_on_mislabelled_release_moves_to_fmp_period(db):
    """Euro Area PPI 8.2% typed (29 Oct) on the calendar row for the 5 Nov release, which was labelled
    October. FMP filled that 5 Nov release as September: the typed copy goes to September."""
    from app.models import EconomicEvent
    from app.services import data_access as da
    from app.services.macro_edit import fix_too_new_periods

    rel_time = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
    ind = _fmp_at(db, "EA_PPI_MOM", "2026-09", 2.5, rel_time)
    typed = _typed(db, ind, "2026-10", 8.2, datetime(2026, 10, 29, 9, tzinfo=timezone.utc))
    db.get(EconomicEvent, typed.event_id).scheduled_at = rel_time
    typed.verification_status = "VERIFIED"
    db.commit()
    fix_too_new_periods(db)
    rel = da.latest_current(db, ind.id)
    assert rel.reference_period == "2026-09" and rel.actual == 2.5
    assert da.event_for(db, ind.id, "2026-10") is None


def test_typed_rate_for_same_meeting_is_retired(db):
    """ECB rate typed as '2026-10' for the 29 Oct meeting that FMP filed as '2026-11': one meeting, one row."""
    from app.models import EconomicEvent
    from app.services import data_access as da
    from app.services.macro_edit import fix_too_new_periods

    when = datetime(2026, 10, 29, 13, 15, tzinfo=timezone.utc)
    ind = _fmp_at(db, "EA_ECB_RATE", "2026-11", 2.5, when)
    ind.frequency = "monthly"  # the repair handles monthly / quarterly rows
    typed = _typed(db, ind, "2026-10", 2.5, when)
    db.get(EconomicEvent, typed.event_id).scheduled_at = when
    db.commit()
    fix_too_new_periods(db)
    db.refresh(typed)
    assert typed.is_current is False and typed.reference_period == "2026-11"


def test_weekly_claims_filed_by_week(db, monkeypatch):
    """FMP's claims for the week to 7 Nov were filed under an event labelled '2026-10', so 31 Oct showed as
    newest. The weekly figure goes to its week."""
    from sqlalchemy import select

    from app.config import settings
    from app.ingestion import markets
    from app.models import EconomicEvent, Source
    from app.services import data_access as da

    src = db.scalar(select(Source).where(Source.key == "fmp"))
    ind = da.indicator_by_code(db, "US_JOBLESS_CLAIMS")
    now = datetime.now(timezone.utc).replace(hour=13, minute=30, second=0, microsecond=0)
    when = now - timedelta(days=(now.weekday() - 3) % 7 or 7)       # last Thursday
    db.add(EconomicEvent(indicator_id=ind.id, reference_period=f"{when.year}-{when.month:02d}",
                         importance="high", scheduled_at=when))
    db.commit()
    first = (date.today() - timedelta(days=markets.FMP_LOOKBACK_DAYS)).isoformat() + " 00:00:00"
    rows = [_item("Initial Jobless Claims", "US", "K", 200.0, 195.0, when=when.strftime("%Y-%m-%d %H:%M:%S"))] + \
        [_item("Some Auction", "US", "%", 1.0, when=first) for _ in range(120)]
    monkeypatch.setattr(settings, "fmp_api_key", "x")
    monkeypatch.setattr(markets, "_fmp_get", lambda params: rows)
    markets.run_fmp(db, src)
    rel = da.latest_current(db, ind.id)
    assert rel.actual == 200.0 and len(rel.reference_period) == 10


def test_japan_core_cpi_is_the_national_figure(match):
    assert match(_item("Core Inflation Rate YoY (Sep)", "JP", "%")) == "JP_CORE_CPI_YOY"
    assert match(_item("Tokyo Core CPI YoY (Oct)", "JP", "%")) is None


def test_fmp_replaces_a_confirmed_typed_number(db):
    """You asked for the calendar's figure to replace numbers you confirmed yourself, too."""
    from app.services import data_access as da

    ind = _fmp_at(db, "GB_PPI_YOY", "2026-09", 8.3, datetime(2026, 10, 15, 6, tzinfo=timezone.utc))
    typed = _typed(db, ind, "2026-10", 9.0, datetime(2026, 11, 17, 9, tzinfo=timezone.utc))
    typed.verification_status = "USER_CONFIRMED"
    db.commit()
    _fmp_at(db, "GB_PPI_YOY", "2026-10", 10.8, datetime(2026, 11, 18, 7, tzinfo=timezone.utc))
    db.commit()
    rel = da.latest_current(db, ind.id)
    assert rel.actual == 10.8 and rel.input_method == "automated"


def test_typed_before_its_release_came_out_is_retired(db):
    """US JOLTS 7.523 typed on 10 Nov as October; the calendar dates October's release in December, so it
    was September's figure (out 3 Nov)."""
    from app.models import EconomicEvent
    from app.services import data_access as da
    from app.services.macro_edit import fix_too_new_periods

    ind = _fmp_at(db, "US_JOLTS", "2026-09", 7.523, datetime(2026, 11, 3, 15, tzinfo=timezone.utc))
    typed = _typed(db, ind, "2026-10", 7.523, datetime(2026, 11, 10, 9, tzinfo=timezone.utc))
    db.get(EconomicEvent, typed.event_id).scheduled_at = datetime(2026, 12, 8, 15, tzinfo=timezone.utc)
    db.commit()
    fix_too_new_periods(db)
    rel = da.latest_current(db, ind.id)
    assert rel.reference_period == "2026-09" and rel.input_method == "automated"


def test_one_bad_release_never_fails_the_run(db, monkeypatch):
    from sqlalchemy import select

    from app.config import settings
    from app.ingestion import markets
    from app.models import Source
    from app.services import data_access as da

    src = db.scalar(select(Source).where(Source.key == "fmp"))
    when = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    first = (date.today() - timedelta(days=markets.FMP_LOOKBACK_DAYS)).isoformat() + " 00:00:00"
    rows = [_item("ISM Manufacturing PMI", "US", None, 55.5, when=when),
            _item("Non Farm Payrolls", "US", "K", 165.0, when=when)] + \
        [_item("Some Auction", "US", "%", 1.0, when=first) for _ in range(120)]
    real = markets.fmp_event

    def flaky(db_, ind, when_, name):
        if ind.code == "US_NFP":
            raise RuntimeError("duplicate key value violates unique constraint")
        return real(db_, ind, when_, name)

    monkeypatch.setattr(settings, "fmp_api_key", "x")
    monkeypatch.setattr(markets, "_fmp_get", lambda params: rows)
    monkeypatch.setattr(markets, "fmp_event", flaky)
    n, warning = markets.run_fmp(db, src)
    assert "US_NFP" in warning and n > 0
    assert da.latest_current(db, da.indicator_by_code(db, "US_ISM_MANUF").id).actual == 55.5
