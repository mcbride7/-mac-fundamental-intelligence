import math
from datetime import date, timedelta

from app.analytics import risk as rk


def _calm(n=300):
    """A calm year: low VIX, tight spreads, rising stocks, AUD/JPY up, EM FX firm, gold flat."""
    return {
        "vix": [20 - 6 * i / n for i in range(n)],          # falling to 14
        "hy_oas": [4.0 - 1.0 * i / n for i in range(n)],     # tightening
        "spx": [5000 * (1 + 0.0015) ** i for i in range(n)],
        "usdjpy": [140 * (1 + 0.0004) ** i for i in range(n)],
        "usdchf": [0.88 * (1 + 0.0003) ** i for i in range(n)],
        "audusd": [0.65 * (1 + 0.0003) ** i for i in range(n)],
        "usdzar": [18.5 * (1 - 0.0004) ** i for i in range(n)],
        "usdmxn": [17.0 * (1 - 0.0004) ** i for i in range(n)],
        "gold": [2400.0] * n,
        "us10y": [4.0 + 0.002 * i for i in range(n)],
    }


def _panic(n=300):
    s = _calm(n)
    for k, f in (("vix", 2.2), ("hy_oas", 1.8)):
        s[k][-15:] = [v * f for v in s[k][-15:]]
    for k, f in (("spx", 0.85), ("audusd", 0.92), ("usdjpy", 0.93), ("usdchf", 0.95), ("us10y", 0.85)):
        s[k][-15:] = [v * f for v in s[k][-15:]]
    for k in ("usdzar", "usdmxn"):
        s[k][-15:] = [v * 1.08 for v in s[k][-15:]]
    s["gold"][-15:] = [v * 1.06 for v in s["gold"][-15:]]
    return s


def test_calm_market_is_risk_on():
    r = rk.evaluate(_calm())
    assert r.label == "Risk-On" and r.score >= 60 and r.coverage == 1.0 and not r.missing


def test_panic_is_risk_off():
    r = rk.evaluate(_panic())
    assert r.label == "Risk-Off" and r.score <= 40
    by = {c.key: c.score for c in r.components}
    assert by["vix"] < 0 and by["credit"] < 0 and by["safe_havens"] < 0 and by["em_fx"] < 0 and by["gold_vs_stocks"] < 0


def test_missing_signals_and_divergence():
    s = _calm()
    for k in ("gold", "usdzar", "usdmxn", "us10y"):
        s.pop(k)
    r = rk.evaluate(s)
    assert "Gold vs stocks" in r.missing and r.coverage < 1 and r.score is not None
    mixed = _calm()
    mixed["vix"][-10:] = [v * 2.5 for v in mixed["vix"][-10:]]   # fear in options...
    mixed["hy_oas"][-10:] = [v * 2.0 for v in mixed["hy_oas"][-10:]]
    r = rk.evaluate(mixed)                                         # ...while stocks and FX still look fine
    assert r.divergence and any("disagree" in n for n in r.notes)
    assert rk.evaluate({}).label == "No data"


def test_job_stores_reading_and_alerts_on_flip(client, db, monkeypatch):
    from app.models import Alert, RiskSentiment
    from app.services import risk_sentiment as rs

    start = date(2025, 8, 1)

    def fake(series, _start):
        name = next(k for k, (code, _) in rs.FRED_SERIES.items() if code == series)
        vals = (state["data"]).get(name, [])
        return [(start + timedelta(days=i), v) for i, v in enumerate(vals)]

    import app.ingestion.fred as fred
    state = {"data": _calm()}
    monkeypatch.setattr(fred, "fetch_observations", fake)
    monkeypatch.setattr(rs.settings, "twelvedata_api_key", "")
    src = db.query(rs.Source).filter_by(key="risk").one()
    rs.run_risk(db, src)
    first = rs.latest_reading(db)
    assert first.label == "Risk-On"
    # new data arrives: replace the stored series with the panic path
    db.query(rs.IndicatorObservation).filter(rs.IndicatorObservation.series.like("RISK:%")).delete()
    db.commit()
    state["data"] = _panic()
    rs.run_risk(db, src)
    assert rs.latest_reading(db).label == "Risk-Off"
    al = db.query(Alert).filter_by(kind="risk_sentiment").one()
    assert al.severity == "HIGH" and "Risk-Off" in al.title
    d = client.get("/api/macro/risk").json()
    assert d["current"]["label"] == "Risk-Off" and len(d["current"]["components"]) >= 7 and d["history"]
    reg = client.get("/api/macro/regime").json()["current"]
    assert reg["signals"].get("risk") == "Risk-Off"


def test_daily_evaluation_lists():
    on = rk.daily_evaluation("Risk-On")
    assert on["bias"] == "Risk On" and "AUD" in on["bullish"] and "JPY" in on["bearish"]
    off = rk.daily_evaluation("Risk-Off")
    assert "JPY" in off["bullish"] and "AUD" in off["bearish"]
    mixed = rk.daily_evaluation("Neutral", {"USD": 2, "EUR": -1, "GBP": 0, "JPY": 1})
    assert mixed["bias"] == "Mixed" and mixed["bullish"] == ["USD", "JPY"] and mixed["bearish"] == ["EUR"]
