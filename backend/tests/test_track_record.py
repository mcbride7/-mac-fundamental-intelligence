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
