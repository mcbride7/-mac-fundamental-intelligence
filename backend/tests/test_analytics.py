from app.analytics import forecast as fx
from app.analytics import policy as px
from app.analytics import scenarios as scx
from app.analytics import statement as sx
from app.analytics import surprise as su
from app.analytics import trading as tx
from app.core.enums import Grade
from app.core.verification import DataPointStatus, apply_cap, evidence_quality, evidence_weight, grade_cap
from app.services.validation import validate_release

PREV = ("Recent indicators suggest that economic activity has continued to expand at a solid pace. Job gains have "
        "remained strong, and the unemployment rate has remained low. Inflation remains elevated. In support of its "
        "goals, the Committee decided to maintain the target range for the federal funds rate at 5-1/4 to 5-1/2 "
        "percent. The Committee does not expect it will be appropriate to reduce the target range until it has "
        "gained greater confidence that inflation is moving sustainably toward 2 percent.")
NEW = ("Recent indicators suggest that economic activity has continued to expand at a solid pace. Job gains have "
       "slowed, and the unemployment rate has moved up but remains low. Inflation has moderated but remains "
       "somewhat elevated. In light of the progress on inflation and the balance of risks, the Committee decided to "
       "lower the target range for the federal funds rate by 1/2 percentage point to 4-3/4 to 5 percent.")


def test_statement_comparison_detects_dovish_shift():
    c = sx.compare(PREV, NEW)
    assert c.direction == "Dovish"
    assert c.tone_shift < 0
    assert c.summary["unchanged"] == 1
    kinds = {ch["type"] for ch in c.changes}
    assert "modified" in kinds and "removed" in kinds
    infl = next(ch for ch in c.changes if ch["previous"] == "Inflation remains elevated.")
    assert infl["direction"] == "Dovish" and "Inflation" in infl["categories"]
    assert any(d["op"] == "insert" for d in infl["diff"])
    assert all(ch["importance"] in ("Low", "Medium", "High", "Critical") for ch in c.changes)


def test_surprise_classification():
    r = su.evaluate(3.4, 3.1, 3.0, [0.1, -0.1, 0.0, 0.1, -0.1, 0.05], [], "%", "yoy", "hawkish")
    assert r.market_surprise == 0.3 and r.cb_surprise == 0.4
    assert r.classification.startswith("Major Upside") and r.policy_direction == "Hawkish"
    r = su.evaluate(4.5, 4.2, None, [], [0.1, 0.1, 0.0, 0.1, 0.0, 0.1], "%", "level", "dovish")
    assert r.policy_direction == "Dovish"  # higher unemployment is dovish


def test_three_way_and_classification():
    t = fx.three_way(3.4, 3.0, 3.1, None, "inflation")
    assert t.cb_error == 0.4 and t.market_error == 0.3 and t.more_accurate == "market"
    assert t.cb_classification == "Significantly Above Projection"


def test_accuracy_bias_revisions():
    a = fx.accuracy([0.3, -0.1, 0.4, 0.2], "inflation")
    assert 0 < a.score < 100 and a.n == 4
    b = fx.bias([0.3, 0.4, 0.2, 0.5, 0.3, 0.4], "inflation")
    assert b.classification == "Inflation underestimation"
    assert fx.bias([0.1, -0.1, 0.05, -0.05], "gdp").classification == "Neutral"
    r = fx.revision_momentum([1.8, 1.5, 1.2, 0.9], "gdp")
    assert r.momentum == "NEGATIVE" and "deteriorating" in r.interpretation
    assert fx.revision_momentum([2.1, 2.4, 2.7, 3.0], "inflation").momentum == "POSITIVE"


def test_policy_implication_tradeoff():
    r = fx.policy_implication({"inflation": 0.6, "gdp": -0.4, "unemployment": -0.4})
    assert r["overall"].startswith("Mixed")
    assert "caution" in r["explanation"][0]


def test_policy_score_and_shift():
    hawk = px.score(px.PolicyInputs(inflation=3.5, inflation_target=2.0, inflation_vs_projection=0.5,
                                    last_decision="HIKE", last_change_bps=25, statement_tone=40,
                                    implied_12m_change_bps=25, policy_rate=5.0))
    dove = px.score(px.PolicyInputs(inflation=1.2, inflation_target=2.0, last_decision="CUT", statement_tone=-40,
                                    implied_12m_change_bps=-100, policy_rate=1.0))
    assert hawk.score > 60 > 40 > dove.score
    assert hawk.direction == "RESTRICTIVE"
    assert px.shift(72, 58) == (-14, "Moderately Dovish Shift")
    s, label = px.cb_surprise_score(-25, 0, -20, 30)
    assert s > 40 and "Hawkish" in label


def test_verification_weights_and_caps():
    assert evidence_weight("VERIFIED") == 1.0
    assert evidence_weight("USER_CONFIRMED", "OFFICIAL_SOURCE") > evidence_weight("USER_CONFIRMED", "NO_SOURCE")
    assert evidence_weight("UNVERIFIED", None, 60) < evidence_weight("UNVERIFIED")
    assert evidence_weight("CONFLICT") == 0
    pts = [DataPointStatus("VERIFIED"), DataPointStatus("UNVERIFIED")]
    cap, _, label = grade_cap(pts)
    assert cap == Grade.A and label == "PENDING VERIFICATION"
    assert apply_cap(Grade.A_PLUS, cap) == Grade.A
    assert grade_cap([DataPointStatus("USER_CONFIRMED", "OFFICIAL_SOURCE")])[0] is None
    assert grade_cap([DataPointStatus("USER_CONFIRMED", "NO_SOURCE")])[0] == Grade.A
    assert grade_cap([DataPointStatus("CONFLICT")])[0] == Grade.NO_TRADE
    assert evidence_quality([DataPointStatus("VERIFIED")]) == 100.0


def test_confluence_grade_and_no_trade():
    usd = tx.Side("USD", policy_score=78, policy_rate=5.25, implied_change_bps=0, inflation_gap=1.4,
                  growth_component=2, y2=4.6, y2_change_1m_bps=20, surprise_index=0.8, employment_component=2)
    eur = tx.Side("EUR", policy_score=42, policy_rate=3.0, implied_change_bps=-75, inflation_gap=0.2,
                  growth_component=-2, y2=2.4, y2_change_1m_bps=-10, surprise_index=-0.6, employment_component=-1)
    c = tx.confluence(eur, usd)  # EURUSD
    assert c.direction == "SHORT" and c.total < -60 and c.agreement >= 0.9
    assert tx.grade(c.total, c.agreement) in (Grade.A, Grade.A_PLUS)
    reasons = tx.no_trade_reasons(c, tx.NoTradeInputs(
        pending_events=[{"name": "US CPI", "hours_until": 6, "importance": "high"}], available_factors=8,
        scenario_gap=40))
    assert any("pending" in r for r in reasons)
    weak = tx.confluence(tx.Side("EUR", policy_score=50), tx.Side("USD", policy_score=52))
    assert any("too few" in r.lower() or "weak" in r.lower()
               for r in tx.no_trade_reasons(weak, tx.NoTradeInputs(available_factors=1)))


def test_scenarios_probabilities_sum_and_triggers():
    p = scx.probabilities(-70, risk_off=False)
    assert sum(p.values()) == 100 and p["base"] > p["opposite"]
    ctx = scx.ScenarioContext("EURUSD", "EUR", "USD", "ECB", "FED", -70, {"central_bank_divergence": -20},
                              metrics={"POLICY:FED": 78, "POLICY:ECB": 42, "SPREAD2Y:EUR-USD": -2.2})
    out = scx.build(ctx)
    assert [s.kind for s in out] == ["base", "bearish", "bullish", "risk"]
    assert out[0].direction == "down"
    inv = [t for t in out[0].triggers if t["trigger_type"] == "invalidation"]
    assert inv and all(scx.evaluate_trigger(t, ctx.metrics) == "not_met" for t in inv)


def test_validation_catches_decimal_shift_and_future():
    w = validate_release(indicator_code="US_CPI_YOY", indicator_unit="%", indicator_transform="yoy",
                         indicator_frequency="monthly", actual=34.0, previous=3.2, consensus=3.1,
                         reference_period="2026-09", released_at=None, history=[3.0, 3.1, 3.2],
                         existing_same_period=[], parsed_transform="mom")
    codes = {x["code"] for x in w}
    assert {"DECIMAL_SHIFT", "TRANSFORM_MISMATCH", "CONSENSUS_SCALE"} <= codes
    w = validate_release(indicator_code="US_CPI_YOY", indicator_unit="%", indicator_transform="yoy",
                         indicator_frequency="monthly", actual=3.4, previous=3.2, consensus=None,
                         reference_period="2099-01", released_at=None, history=[], existing_same_period=[
                             {"id": 1, "actual": 3.3, "verification_status": "VERIFIED"}])
    codes = {x["code"] for x in w}
    assert "FUTURE_PERIOD" in codes and "CONFLICT_EXISTING" in codes
