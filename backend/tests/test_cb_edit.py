def _ov(client, code):
    return client.get(f"/api/central-banks/{code}").json()


def test_rate_for_bank_without_indicator(client):
    e = lambda **b: client.patch("/api/central-banks/BOC/overview", json=b)
    assert e(field="current_rate", value="2.75").status_code == 200
    r = e(field="current_rate", value="2.5%")
    assert r.status_code == 200, r.text
    d = _ov(client, "BOC")
    assert d["current_rate"] == 2.5 and d["previous_rate"] == 2.75
    assert d["last_decision"] == "CUT" and d["last_change_bps"] == -25 and d["rate_from_indicator"] is False
    assert e(field="last_decision", value="hold").status_code == 200
    assert _ov(client, "BOC")["last_decision"] == "HOLD"
    assert e(field="current_rate", value="abc").status_code == 400
    assert e(field="inflation_target", value="2.5").status_code == 200
    assert _ov(client, "BOC")["inflation_target"] == 2.5


def test_rate_for_bank_with_indicator_goes_through_checks(client):
    e = lambda **b: client.patch("/api/central-banks/FED/overview", json=b)
    assert e(field="current_rate", value=4.5, period="2026-07").status_code == 200
    r = e(field="current_rate", value=4.25, period="2026-09")
    assert r.status_code == 200, r.text
    d = _ov(client, "FED")
    assert d["current_rate"] == 4.25 and d["last_decision"] == "CUT" and d["previous_rate"] == 4.5
    src = [s for s in d["data_status"]["sources"] if s["label"] == "Policy rate"][0]
    assert src["period"] == "2026-09" and src["input_method"] != "automated"
    # the last decision can also be set by hand (e.g. a hold the rate history can't show yet)
    assert e(field="last_decision", value="HOLD").status_code == 200
    d = _ov(client, "FED")
    assert d["last_decision"] == "HOLD" and d["last_change_bps"] == 0 and d["current_rate"] == 4.25
    assert e(field="previous_rate", value=5).status_code == 400
    assert e(field="current_rate", value=4, period="Sept").status_code == 400


def test_release_and_meeting_edits(client):
    e = lambda **b: client.patch("/api/central-banks/ECB/overview", json=b)
    assert e(field="release", indicator_code="EA_HICP_YOY", period="2026-08", value="2.1").status_code == 200
    r = e(field="release", indicator_code="EA_HICP_YOY", period="2026-09", value="2.2")
    assert r.status_code == 200, r.text
    assert _ov(client, "ECB")["inflation"] == 2.2
    # an implausible jump asks for a reason first (same rule as the calendar)
    r = e(field="release", indicator_code="EA_HICP_YOY", period="2026-09", value="45")
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["needs"] == "override_reason"
    r = e(field="release", indicator_code="EA_HICP_YOY", period="2026-09", value="2.3", reason="revised")
    assert r.status_code == 200 and _ov(client, "ECB")["inflation"] == 2.3
    assert e(field="expected_decision", value="CUT").status_code == 400  # no meeting yet
    assert e(field="next_meeting", value="2099-12-17").status_code == 200
    assert e(field="expected_decision", value="CUT").status_code == 200
    d = _ov(client, "ECB")
    assert d["next_meeting"] == "2099-12-17" and d["expected_decision"] == "CUT"
    assert e(field="next_meeting", value="2001-01-01").status_code == 400
