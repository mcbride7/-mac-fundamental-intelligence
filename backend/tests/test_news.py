from datetime import timedelta

from app.services import news

RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>Fed signals no rush to cut as inflation rises</title><link>https://x.test/a</link>
<pubDate>Mon, 26 Oct 2026 10:00:00 GMT</pubDate><description>&lt;p&gt;Powell said rate hikes are not ruled out.&lt;/p&gt;</description></item>
<item><title>EUR/USD tumbles as ECB flags more rate cuts</title><link>https://x.test/b</link>
<pubDate>Mon, 26 Oct 2026 11:00:00 GMT</pubDate><description>Euro slides; recession fears grow.</description></item>
</channel></rss>"""


def test_classify():
    a = news.classify("Fed signals no rush to cut as inflation rises", "Powell said rate hikes are not ruled out.")
    assert "USD" in a["currencies"] and a["tone"] == "hawkish" and "Central banks" in a["topics"] and "Inflation" in a["topics"]
    b = news.classify("EUR/USD tumbles as ECB flags more rate cuts", "Euro slides; recession fears grow.")
    assert {"EUR", "USD"} <= set(b["currencies"]) and b["tone"] == "dovish" and b["risk"] == "risk_off"
    c = news.classify("Gold hits record high as yen rallies")
    assert {"XAU", "JPY"} <= set(c["currencies"]) and c["risk"] == "risk_on"
    assert "USD" not in news.classify("Shortcut to Brussels talks")["currencies"]


def test_parse_store_and_api(client, db, monkeypatch):
    from app.db import utcnow

    items = news.parse_rss(RSS)
    assert len(items) == 2 and items[0]["summary"].startswith("Powell")
    for it in items:
        it["published"] = utcnow() - timedelta(hours=2)
    monkeypatch.setattr(news, "fetch_rss", lambda url: items if "federalreserve" in url else [])
    r = client.post("/api/news/refresh")
    assert r.json()["status"] == "OK" and r.json()["records"] == 2
    assert client.post("/api/news/refresh").json()["records"] == 0  # no duplicates
    d = client.get("/api/news").json()
    assert d["total"] == 2 and d["feeds"]["fed"]["ok"] and d["feeds"]["finnhub"]["ok"] is False
    assert client.get("/api/news?currency=EUR").json()["total"] == 1
    assert client.get("/api/news?tone=hawkish").json()["articles"][0]["title"].startswith("Fed")
    assert d["tone"]["USD"]["articles"] == 2


def test_news_tone_column(db):
    from app.db import utcnow
    from app.models import NewsArticle
    from app.services import setups_table as tb

    for i in range(3):
        db.add(NewsArticle(uid=f"u{i}", title=f"BoE hawkish {i}", source_name="t", feed="t", published_at=utcnow(),
                           currencies=["GBP"], topics=[], tone="hawkish"))
    db.commit()
    assert news.tone_cells(db)["GBP"] == 1
    tb.clear_cache()
    rows = {r["symbol"]: r for r in tb.compute(db)["rows"]}
    assert rows["GBPUSD"]["cells"]["news"] == 1 and rows["EURGBP"]["cells"]["news"] == -1
    assert rows["EURUSD"]["cells"]["news"] is None


def test_pair_code_alone_gets_no_tone():
    a = news.classify("GBP/USD rallies after stronger-than-expected UK wages")
    assert {"GBP", "USD"} <= set(a["currencies"]) and a["tone"] == "hawkish"
    assert a["tone_currencies"] == ["GBP"]


def test_tone_breakdown(db):
    from app.db import utcnow
    from app.models import NewsArticle

    rows = [("Fed signals more hikes", ["USD"], ["USD"], "hawkish"),
            ("GBP/USD rallies on strong UK wages", ["GBP", "USD"], ["GBP"], "hawkish"),
            ("Powell speaks today", ["USD"], ["USD"], "neutral")]
    for i, (t, cc, tc, tone) in enumerate(rows):
        db.add(NewsArticle(uid=f"b{i}", title=t, source_name="t", feed="t", published_at=utcnow(), currencies=cc,
                           tone_currencies=tc, topics=[], tone=tone))
    db.commit()
    usd = news.listing(db)["tone"]["USD"]
    pts = {b["title"]: b["points"] for b in usd["breakdown"]}
    assert pts == {"Fed signals more hikes": 1, "GBP/USD rallies on strong UK wages": 0, "Powell speaks today": 0}
    assert usd["net"] == sum(pts.values())
    assert "pair code" in next(b["why"] for b in usd["breakdown"] if b["points"] == 0 and "GBP" in b["title"])
