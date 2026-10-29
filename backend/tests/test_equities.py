import time


def test_equities_feed(client, db, monkeypatch):
    from app.config import settings
    from app.services import equities

    monkeypatch.setattr(settings, "finnhub_api_key", "k")
    monkeypatch.setenv("FINNHUB_DELAY", "0")
    now = int(time.time())
    quotes = {"SPY": {"c": 580.1, "d": 2.3, "dp": 0.4, "h": 581, "l": 575, "o": 576, "pc": 577.8, "t": now},
              "EZA": {"c": 48.2, "d": -0.5, "dp": -1.03, "h": 49, "l": 48, "o": 48.9, "pc": 48.7, "t": now}}
    monkeypatch.setattr(equities, "fetch_quote", lambda s: quotes.get(s, {"c": 0, "t": 0}))
    r = client.post("/api/markets/equities/refresh").json()
    assert r["status"] == "OK" and r["records"] == 2 and "AAPL" in r["warning"]
    d = client.get("/api/markets/equities").json()
    spy = next(x for x in d["rows"] if x["symbol"] == "SPY")
    assert spy["price"] == 580.1 and spy["change_pct"] == 0.4 and spy["group"] == "US indices"
    assert d["breadth"] == {"up": 1, "down": 1}
    quotes["PLTR"] = {"c": 30.5, "d": 1, "dp": 3.4, "h": 31, "l": 29, "o": 29.5, "pc": 29.5, "t": now}
    assert client.post("/api/markets/equities", json={"symbol": "pltr"}).status_code == 200
    d = client.get("/api/markets/equities").json()
    assert "My list" in d["groups"] and next(x for x in d["rows"] if x["symbol"] == "PLTR")["price"] == 30.5
    assert client.post("/api/markets/equities", json={"symbol": "not a ticker!"}).status_code == 400
    assert client.delete("/api/markets/equities/PLTR").status_code == 200
    assert "My list" not in client.get("/api/markets/equities").json()["groups"]
