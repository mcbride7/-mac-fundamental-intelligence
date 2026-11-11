from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def _price(db, sym, ts, px):
    from app.models import MarketPrice

    db.add(MarketPrice(symbol=sym, ts=ts, price=px, asset_class="fx", source="test"))


def test_records_calls_and_scores_them(db):
    from app.services import track_record as tr

    _price(db, "EURUSD", T0 - timedelta(minutes=5), 1.1000)
    db.commit()
    rec = tr.record(db, "EURUSD", "A", "LONG", 62.0, now=T0)
    db.commit()
    assert rec.entry_price == 1.1
    # same call again: not duplicated
    assert tr.record(db, "EURUSD", "A", "LONG", 63.0, now=T0 + timedelta(hours=1)) is None
    _price(db, "EURUSD", T0 + timedelta(days=1), 1.1110)   # +1.0%
    _price(db, "EURUSD", T0 + timedelta(days=5), 1.0945)   # -0.5%
    db.commit()
    n = tr.evaluate(db, now=T0 + timedelta(days=6))
    assert n == 2
    db.refresh(rec)
    assert round(rec.ret_1d, 2) == 1.0 and round(rec.ret_5d, 2) == -0.5 and rec.ret_20d is None
    s = tr.summary(db)
    a = next(r for r in s["by_grade"] if r["grade"] == "A")
    assert a["signals"] == 1 and a["hit_rate_1d"] == 100.0 and a["hit_rate_5d"] == 0.0


def test_short_calls_and_supersede(db):
    from app.services import track_record as tr

    _price(db, "USDJPY", T0, 150.0)
    db.commit()
    short = tr.record(db, "USDJPY", "B", "SHORT", -48.0, now=T0)
    db.commit()
    _price(db, "USDJPY", T0 + timedelta(days=1), 148.5)   # price fell 1% -> short made +1%
    db.commit()
    tr.evaluate(db, now=T0 + timedelta(days=1, hours=1))
    db.refresh(short)
    assert round(short.ret_1d, 2) == 1.0
    tr.record(db, "USDJPY", "NO TRADE", "NONE", -10.0, now=T0 + timedelta(days=2))
    db.commit()
    db.refresh(short)
    assert short.superseded_at is not None and tr.latest_open(db, "USDJPY") is None


def test_missing_price_is_noted_not_guessed(db):
    from app.services import track_record as tr

    rec = tr.record(db, "NZDUSD", "C", "LONG", 31.0, now=T0)
    db.commit()
    assert rec.entry_price is None and "No price" in rec.note
    assert tr.evaluate(db, now=T0 + timedelta(days=30)) == 0


def test_endpoint(client):
    r = client.get("/api/track-record")
    assert r.status_code == 200 and {g["grade"] for g in r.json()["by_grade"]} == {"A+", "A", "B", "C"}


def test_cross_pairs_priced_from_usd_legs(db):
    from app.services import track_record as tr

    _price(db, "EURUSD", T0, 1.10)
    _price(db, "GBPUSD", T0, 1.25)
    _price(db, "USDJPY", T0, 150.0)
    db.commit()
    assert round(tr._price_near(db, "EURGBP", T0).price, 4) == 0.88
    assert round(tr._price_near(db, "EURJPY", T0).price, 2) == 165.0


def test_trade_plan_levels_type_and_outcome(client, db):
    from app.services import track_record as tr

    # 14 days of ~0.5% daily moves before the call
    px = 1.1000
    for i in range(15, 0, -1):
        px *= 1.005 if i % 2 else 0.995
        _price(db, "EURUSD", T0 - timedelta(days=i), round(px, 5))
    _price(db, "EURUSD", T0 - timedelta(minutes=5), 1.1000)
    db.commit()
    rec = tr.record(db, "EURUSD", "A", "LONG", 62.0, now=T0)
    db.commit()
    plan = tr.plan_for(db, rec)
    assert plan.trade_type == "swing" and 0.5 < plan.atr_pct < 0.7
    assert plan.stop_loss < 1.1 < plan.take_profit
    assert abs((plan.take_profit - 1.1) / (1.1 - plan.stop_loss) - 2) < 0.01  # 1 : 2
    # price runs up to the target three days later
    _price(db, "EURUSD", T0 + timedelta(days=1), 1.1010)
    _price(db, "EURUSD", T0 + timedelta(days=3), plan.take_profit + 0.0005)
    db.commit()
    row = next(r for r in client.get("/api/track-record").json()["recent"] if r["id"] == rec.id)
    assert row["trade_type"] == "swing" and row["outcome"] == "target" and row["result_r"] == 2.0 and row["risk_reward"] == 2.0
    a = next(g for g in client.get("/api/track-record").json()["by_grade"] if g["grade"] == "A")
    assert a["targets_hit"] == 1 and a["avg_r"] == 2.0
    # switch to a day trade by hand: tighter levels, re-checked
    r = client.patch(f"/api/track-record/{rec.id}", json={"trade_type": "day"}).json()
    assert r["trade_type"] == "day" and r["sl_pct"] < row["sl_pct"]
    # own levels; a stop on the wrong side is refused
    assert client.patch(f"/api/track-record/{rec.id}", json={"stop_loss": 1.2}).status_code == 422
    db.expire_all()
    assert tr.plan_for(db, rec).stop_loss < 1.1  # the refused edit was not kept
    r = client.patch(f"/api/track-record/{rec.id}", json={"trade_type": "swing", "stop_loss": 1.09, "take_profit": 1.13}).json()
    assert r["manual"] and r["stop_loss"] == 1.09 and r["take_profit"] == 1.13 and r["outcome"] == "expired"  # 20 days passed without either


def test_grade_c_is_a_day_trade(db):
    from app.services import track_record as tr

    _price(db, "GBPUSD", T0, 1.30)
    db.commit()
    rec = tr.record(db, "GBPUSD", "C", "SHORT", -31.0, now=T0)
    db.commit()
    plan = tr.plan_for(db, rec)
    assert plan.trade_type == "day" and plan.stop_loss is None  # no history to size levels from: left blank


def test_setup_detail_chart_and_snapshot(client, db):
    from app.models import TradeSetup
    from app.services import track_record as tr

    for h in range(-24 * 14, 24 * 10, 6):  # prices every 6h, two weeks before to ten days after
        _price(db, "AUDUSD", T0 + timedelta(hours=h), 0.6500 * (1 + 0.0004 * h / 24 + (0.002 if h % 12 else -0.002)))
    common = dict(asset="AUDUSD", confluence_score=55.0, data_status="complete", primary_driver="RBA hawkish",
                  confirmation=["Close above 0.66"], invalidation=["Close below 0.64"])
    db.add(TradeSetup(as_of=T0 - timedelta(days=3), direction="SHORT", grade="C", factors={}, **common))
    db.add(TradeSetup(as_of=T0 - timedelta(minutes=1), direction="LONG", grade="A",
                      factors={"Central Bank Divergence": 14.0, "Risk Sentiment": -2.5}, **common))
    db.add(TradeSetup(as_of=T0 + timedelta(days=2), direction="SHORT", grade="B", factors={}, **common))
    db.commit()
    rec = tr.record(db, "AUDUSD", "A", "LONG", 55.0, now=T0)
    db.commit()
    d = tr.setup_detail(db, rec.id, now=T0 + timedelta(days=9))
    assert d["call"]["id"] == rec.id and d["call"]["stop_loss"] and d["call"]["take_profit"]
    assert len(d["prices"]) > 50 and d["prices"][0][0] < d["call"]["opened_at"] < d["prices"][-1][0]
    s = d["setup"]
    assert s["grade"] == "A" and s["direction"] == "LONG" and s["primary_driver"] == "RBA hawkish"
    assert s["factors"][0] == {"name": "Central Bank Divergence", "score": 14.0, "max": 20}
    r = client.get(f"/api/track-record/{rec.id}/setup")
    assert r.status_code == 200 and r.json()["setup"]["grade"] == "A"
    assert client.get("/api/track-record/999999/setup").status_code == 404


def test_stop_and_target_use_hourly_highs_and_lows(db):
    """A target touched intraday (high above it) counts, even when no close went beyond it."""
    from app.models.track import PriceBar
    from app.services import track_record as tr

    for i in range(16):  # daily bars: range 1.095-1.105 -> ATR ~0.9%
        db.add(PriceBar(symbol="EURUSD", interval="1day", ts=T0 - timedelta(days=16 - i), open=1.1, high=1.105, low=1.095, close=1.1))
    _price(db, "EURUSD", T0 - timedelta(minutes=5), 1.1)
    db.commit()
    rec = tr.record(db, "EURUSD", "A", "LONG", 62.0, now=T0)
    db.commit()
    plan = tr.plan_for(db, rec)
    assert 0.85 < plan.atr_pct < 0.95  # true range, not close-to-close
    for h in range(1, 6):  # hourly bars after the call; bar 4 spikes through the target, closes back below
        hi = plan.take_profit + 0.001 if h == 4 else 1.101
        db.add(PriceBar(symbol="EURUSD", interval="1hour", ts=T0 + timedelta(hours=h - 1), open=1.1, high=hi, low=1.099, close=1.1))
    db.commit()
    tr.check_plan(db, rec, plan, T0 + timedelta(hours=6))
    assert plan.outcome == "target" and plan.outcome_at == T0 + timedelta(hours=4)
