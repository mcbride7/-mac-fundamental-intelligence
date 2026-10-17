import pytest

from app.ingestion import official as off

JSONSTAT = {
    "id": ["freq", "unit", "coicop18", "geo", "time"], "size": [1, 2, 3, 1, 2],
    "dimension": {
        "freq": {"category": {"index": {"M": 0}, "label": {"M": "Monthly"}}},
        "unit": {"category": {"index": {"I25": 0, "RCH_A": 1},
                              "label": {"I25": "Index, 2025=100", "RCH_A": "Annual rate of change"}}},
        "coicop18": {"category": {"index": {"TOTAL": 0, "CP01": 1, "TOT_X_NRG_FOOD": 2},
                                  "label": {"TOTAL": "All-items HICP", "CP01": "Food",
                                            "TOT_X_NRG_FOOD": "Overall index excluding energy, food, alcohol and tobacco"}}},
        "geo": {"category": {"index": {"EA": 0}, "label": {"EA": "Euro area"}}},
        "time": {"category": {"index": {"2026-07": 0, "2026-08": 1}}},
    },
    # positions: unit*6 + coicop*2 + time
    "value": {"0": 101.0, "1": 101.2, "6": 2.1, "7": 2.2, "10": 2.4, "11": 2.3},
}


def test_jsonstat_selects_by_code_or_label():
    head = off.parse_jsonstat(JSONSTAT, {"unit": ["RCH_A"], "coicop18": ["TOTAL"]})
    assert head == [("2026-07", 2.1), ("2026-08", 2.2)]
    core = off.parse_jsonstat(JSONSTAT, {"unit": ["annual rate of change"],
                                         "coicop18": ["excluding energy, food, alcohol and tobacco"]})
    assert core == [("2026-07", 2.4), ("2026-08", 2.3)]
    with pytest.raises(Exception):
        off.parse_jsonstat(JSONSTAT, {"unit": ["RCH_A"], "coicop18": ["nonexistent"]})


def test_periods():
    assert off._period("2026-08") == "2026-08" and off._period("2026M08") == "2026-08"
    assert off._period("2026-Q2") == "2026Q2" and off._period("2026Q2") == "2026Q2"


def test_ons_months_quarters_and_rolling_labels():
    data = {"months": [{"date": "2026 JUL", "value": "3.8", "label": "2026 JUL"},
                       {"date": "2026 AUG", "value": "3.6", "label": "2026 AUG"},
                       {"date": "2026 SEP", "value": "", "label": "2026 SEP"}],
            "quarters": [{"date": "2026 Q2", "value": "0.3"}]}
    assert off.parse_ons(data) == [("2026-07", 3.8), ("2026-08", 3.6), ("2026Q2", 0.3)]
    # ONS labour market: date is the middle month of a rolling quarter
    lfs = {"months": [{"date": "2026 JUL", "value": "4.8", "label": "2026 JUN-AUG"},
                      {"date": "2025 DEC", "value": "4.4", "label": "2025 NOV-JAN"}]}
    assert off.parse_ons(lfs) == [("2026-01", 4.4), ("2026-08", 4.8)]


def test_statcan_and_helpers():
    data = [{"status": "SUCCESS", "object": {"vectorId": 2062815, "vectorDataPoint": [
        {"refPer": "2026-08-01", "value": 7.1}, {"refPer": "2026-09-01", "value": 7.0}]}},
        {"status": "FAILED", "object": "bad vector"}]
    assert off.parse_statcan(data) == {2062815: [("2026-08", 7.1), ("2026-09", 7.0)]}
    idx = [("2025-09", 160.0), ("2026-08", 164.0), ("2026-09", 164.8)]
    assert off.yoy(idx) == [("2026-09", 3.0)]
    assert off.diff([("2026-07", 20500.0), ("2026-08", 20530.5), ("2026-09", 20510.0)]) == \
        [("2026-08", 30.5), ("2026-09", -20.5)]


def test_abs_sdmx_xml():
    xml = """<?xml version="1.0"?><message:StructureSpecificData xmlns:message="m"><message:DataSet>
      <Obs TIME_PERIOD="2026-08" OBS_VALUE="4.65160785" MEASURE="M13"/>
      <Obs TIME_PERIOD="2026-09" OBS_VALUE="4.71834873" MEASURE="M13"/></message:DataSet></message:StructureSpecificData>"""
    assert off.parse_sdmx_xml(xml) == [("2026-08", 4.65160785), ("2026-09", 4.71834873)]


def test_run_agency_writes_and_verifies(db, monkeypatch):
    from sqlalchemy import select

    from app.models import Source
    from app.services import data_access as da

    agency = off.Agency("ons", [
        off.Series("GB_CPI_YOY", lambda: [("2026-07", 3.8), ("2026-08", 3.6)]),
        off.Series("GB_UNEMPLOYMENT", lambda: (_ for _ in ()).throw(off.SourceUnavailable("ONS mgsx: down"))),
    ])
    src = db.scalar(select(Source).where(Source.key == "ons"))
    n = off.run_agency(db, src, agency)
    ind = da.indicator_by_code(db, "GB_CPI_YOY")
    rel = da.current_release(db, ind.id, "2026-08")
    assert n == 2 and rel.actual == 3.6 and rel.verification_status == "VERIFIED"
    # all series failing -> the run fails with the reason
    bad = off.Agency("ons", [off.Series("GB_CPI_YOY", lambda: (_ for _ in ()).throw(off.SourceUnavailable("x")))])
    with pytest.raises(off.SourceUnavailable):
        off.run_agency(db, src, bad)


def test_every_series_maps_to_a_real_indicator(db):
    from app.services import data_access as da

    for code in off.OFFICIAL_BY_CODE:
        assert da.indicator_by_code(db, code) is not None, code


def test_sources_show_run_now(client):
    srcs = {s["key"]: s for s in client.get("/api/data-health").json()["sources"]}
    for k in ("eurostat", "ons", "statcan", "abs", "fred", "forexfactory"):
        assert srcs[k]["runnable"], k
    assert not srcs["bls"]["runnable"]


class _Resp:
    def __init__(self, status, body="", js=None):
        self.status_code, self.text, self._js = status, body, js

    def json(self):
        if self._js is None:
            raise ValueError("no json")
        return self._js


def test_statcan_falls_back_to_get(monkeypatch):
    ok = [{"status": "SUCCESS", "object": {"vectorId": 2062815, "vectorDataPoint": [
        {"refPer": "2026-08-01", "value": 7.1}, {"refPer": "2026-09-01", "value": 7.0}]}}]
    monkeypatch.setattr(off.requests, "post", lambda *a, **k: _Resp(404, "<html>Not Found</html>"))
    monkeypatch.setattr(off.requests, "get", lambda *a, **k: _Resp(200, "", ok))
    assert off._statcan(2062815, 4) == [("2026-08", 7.1), ("2026-09", 7.0)]
    monkeypatch.setattr(off.requests, "get", lambda *a, **k: _Resp(404, "Not Found"))
    with pytest.raises(off.SourceUnavailable) as e:
        off._statcan(2062815, 4)
    assert "404" in str(e.value)


def test_abs_tries_other_query_forms(monkeypatch):
    calls = []
    xml = '<m xmlns="x"><Obs TIME_PERIOD="2026-09" OBS_VALUE="4.7"/></m>'

    def fake_get(url, params=None, **k):
        calls.append(params)
        return _Resp(404, "NoRecordsFound") if len(calls) == 1 else _Resp(200, xml)

    monkeypatch.setattr(off.requests, "get", fake_get)
    assert off._abs("LF,1.0.0", "M13.3.1599.20.AUS.M") == [("2026-09", 4.7)]
    assert len(calls) == 2
