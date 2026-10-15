from datetime import date

from app.seed import INDICATORS
from app.services.extraction.normalizer import IndicatorRef, convert_unit, map_indicator
from app.services.extraction.text_parser import parse_number, parse_text

TODAY = date(2026, 10, 8)
REFS = [IndicatorRef(r[0], r[1], r[2], r[3], r[5], r[8], r[10]) for r in INDICATORS]


def test_parse_number_locales():
    assert parse_number("3,4") == 3.4
    assert parse_number("1,234.5") == 1234.5
    assert parse_number("1.234,5") == 1234.5
    assert parse_number("−0.2") == -0.2
    assert parse_number("250") == 250


def test_natural_language_example_from_spec():
    r = parse_text("US CPI September 3.4% y/y, core 3.1%, consensus 3.1%, previous 3.2%", TODAY)
    assert r.content_type == "economic_release"
    head, core = r.rows
    assert head.fields["actual"] == 3.4 and head.fields["consensus"] == 3.1 and head.fields["previous"] == 3.2
    assert head.fields["reference_period"] == "2026-09" and head.fields["country"] == "US"
    assert core.fields["actual"] == 3.1 and "core" in core.fields["indicator_text"].lower()


def test_decimal_comma_and_label_after_value():
    r = parse_text("SA CPI August 3,4% previous 3,5%", TODAY).rows[0]
    assert r.fields["actual"] == 3.4 and r.fields["previous"] == 3.5 and r.fields["country"] == "ZA"
    r = parse_text("Euro area HICP flash Sep 2.1% vs 2.2% expected, prior 2.0%", TODAY).rows[0]
    assert (r.fields["actual"], r.fields["consensus"], r.fields["previous"]) == (2.1, 2.2, 2.0)


def test_calendar_table_with_header_and_missing_actual():
    text = """Time Cur Event Actual Forecast Previous
08:30 USD CPI m/m 0.4% 0.3% 0.2%
08:30 USD Core CPI y/y 3.1% 3.0% 3.0%
10:00 EUR Unemployment Rate 6.3% 6.4%"""
    r = parse_text(text, TODAY)
    assert r.content_type == "calendar" and len(r.rows) == 3
    assert r.rows[0].fields["actual"] == 0.4 and r.rows[0].fields["currency"] == "USD"
    assert "actual" not in r.rows[2].fields and r.rows[2].warnings


def test_csv_projection_rates_prices():
    csv = "Indicator,Period,Actual,Previous,Forecast,Unit,Date\nUS CPI y/y,2026-09,3.4,3.2,3.1,%,2026-10-08"
    r = parse_text(csv, TODAY)
    assert r.rows[0].fields["actual"] == 3.4 and r.rows[0].fields["release_date"] == "2026-10-08"
    sep = """Summary of Economic Projections
Variable 2026 2027 2028 Longer run
Change in real GDP 1.4 1.6 1.8 1.8
Core PCE inflation 3.0 2.5 2.1"""
    r = parse_text(sep, TODAY)
    assert r.content_type == "cb_projections"
    vals = {(x.fields["variable"], x.fields["target_period"]): x.fields["value"] for x in r.rows}
    assert vals[("gdp", "2026")] == 1.4 and vals[("core_inflation", "2027")] == 2.5
    r = parse_text("FOMC pricing probabilities: cut 20%, hold 65%, hike 15%", TODAY)
    assert r.rows[0].fields == {"prob_cut": 20.0, "prob_hold": 65.0, "prob_hike": 15.0, "central_bank_code": "FED"}
    r = parse_text("EUR/USD 1.0850\nGold 2,650.5\nUS 10Y 4.25%", TODAY)
    assert r.content_type == "market_prices" and r.rows[2].fields == {"country": "US", "tenor": "10Y",
                                                                      "yield_pct": 4.25}


def test_indicator_mapping():
    assert map_indicator("US CPI", "US", "yoy", REFS)[0] == "US_CPI_YOY"
    assert map_indicator("core US CPI", "US", "yoy", REFS)[0] == "US_CORE_CPI_YOY"
    assert map_indicator("CPI m/m", "US", "mom", REFS)[0] == "US_CPI_MOM"
    assert map_indicator("NFP", None, None, REFS)[0] == "US_NFP"
    assert map_indicator("SA CPI", "ZA", None, REFS)[0] == "ZA_CPI_YOY"
    assert map_indicator("Fed Interest Rate Decision", "US", None, REFS)[0] == "US_FED_RATE"


def test_unit_conversion():
    assert convert_unit(250000, None, "k")[0] == 250.0
    assert convert_unit(0.25, "m", "k")[0] == 250.0
