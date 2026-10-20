from datetime import date

import pytest

from app.ingestion.base import SourceUnavailable
from app.services import cb_shortcuts as cs

FED_PAGE = """
<a href="/newsevents/pressreleases/monetary20260729a.htm">Statement</a>
<a href="/newsevents/pressreleases/monetary20260916a.htm">Statement</a>
<a href="/newsevents/pressreleases/monetary20260916a1.htm">Implementation note</a>
<a href="/monetarypolicy/fomcprojtabl20260617.htm">HTML</a>
<a href="/monetarypolicy/fomcprojtabl20260916.htm">HTML</a>
"""

STATEMENT = ("Recent indicators suggest that economic activity has continued to expand at a solid pace. "
             "Inflation remains somewhat elevated. The Committee decided to maintain the target range.")


def test_every_bank_has_shortcuts(db):
    from app.models import CentralBank

    codes = {b.code for b in db.query(CentralBank)}
    assert codes <= set(cs.CATALOGUE)
    rows = cs.serialize(today=date(2026, 10, 20))
    assert {r["code"] for r in rows} == set(cs.CATALOGUE)
    for r in rows:
        for kind in ("statement", "projections"):
            assert r[kind]["page"].startswith("https://") and "{year}" not in r[kind]["page"]
    boj = next(r for r in rows if r["code"] == "BOJ")
    assert "state_2026" in boj["statement"]["page"]


def test_fed_picks_newest_statement_and_dot_plot():
    base = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    st = cs.find_links(FED_PAGE, base, cs.CATALOGUE["FED"].statement.finder)
    assert st[0] == "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm"
    pr = cs.find_links(FED_PAGE, base, cs.CATALOGUE["FED"].projections.finder)
    assert pr[0].endswith("fomcprojtabl20260916.htm")


def test_month_names_sort_and_text_filter():
    boe = """<a href="/monetary-policy-summary-and-minutes/2026/march-2026">x</a>
             <a href="/monetary-policy-summary-and-minutes/2026/september-2026">x</a>
             <a href="/monetary-policy-summary-and-minutes/2025/december-2025">x</a>"""
    links = cs.find_links(boe, "https://www.bankofengland.co.uk/x", cs.CATALOGUE["BOE"].statement.finder)
    assert links[0].endswith("/2026/september-2026")
    rba = """<a href="/media-releases/2026/mr-26-20.html">Bond purchase update</a>
             <a href="/media-releases/2026/mr-26-18.html">Statement by the Monetary Policy Board: Monetary Policy Decision</a>
             <a href="/media-releases/2026/mr-26-12.html">Statement by the Monetary Policy Board: Monetary Policy Decision</a>"""
    links = cs.find_links(rba, "https://www.rba.gov.au/media-releases/2026/", cs.CATALOGUE["RBA"].statement.finder)
    assert links == ["https://www.rba.gov.au/media-releases/2026/mr-26-18.html",
                     "https://www.rba.gov.au/media-releases/2026/mr-26-12.html"]


def test_suffix_and_rss_links():
    smp = '<a href="/publications/smp/2026/may/">May</a><a href="/publications/smp/2026/aug/">Aug</a>'
    links = cs.find_links(smp, "https://www.rba.gov.au/publications/smp/", cs.CATALOGUE["RBA"].projections.finder)
    assert links[0] == "https://www.rba.gov.au/publications/smp/2026/aug/outlook.html"
    rss = """<item><title>Monetary policy decisions</title>
      <link>https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260910~abc123.en.html</link></item>
      <item><link>https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260723~def456.en.html</link></item>"""
    links = cs.find_links(rss, "https://www.ecb.europa.eu/rss/press.html", cs.CATALOGUE["ECB"].statement.finder)
    assert links[0].endswith("ecb.mp260910~abc123.en.html")


def test_latest_url_tries_last_year(monkeypatch):
    class R:
        def __init__(self, text): self.text = text

    pages = {"https://www.boj.or.jp/en/mopo/mpmdeci/state_2027/index.htm": "<p>nothing yet</p>",
             "https://www.boj.or.jp/en/mopo/mpmdeci/state_2026/index.htm":
                 '<a href="/en/mopo/mpmdeci/mpr_2026/k261030a.pdf">Statement</a>'}
    monkeypatch.setattr(cs, "http_get", lambda url, retries=1: R(pages[url]))
    assert cs.latest_url("BOJ", "statement", date(2027, 1, 5)) == \
        "https://www.boj.or.jp/en/mopo/mpmdeci/mpr_2026/k261030a.pdf"
    with pytest.raises(SourceUnavailable):
        cs.latest_url("PBOC", "projections")


def test_fetch_endpoint_opens_review(client, monkeypatch):
    from app.services.extraction import pipeline

    class R:
        text = FED_PAGE

    monkeypatch.setattr(cs, "http_get", lambda url, retries=1: R())
    fetched = []

    def fake_fetch(url):
        fetched.append(url)
        return f"<html><body><p>{STATEMENT}</p></body></html>".encode(), "text/html"

    monkeypatch.setattr(pipeline, "fetch_url", fake_fetch)
    r = client.get("/api/central-banks/shortcuts")
    assert r.status_code == 200 and len(r.json()) == len(cs.CATALOGUE)

    r = client.post("/api/central-banks/FED/fetch", json={"kind": "statement"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resolved_url"].endswith("monetary20260916a.htm")
    assert fetched == [body["resolved_url"]]
    pt = body["points"][0]
    assert pt["kind"] == "cb_statement" and pt["fields"]["central_bank_code"] == "FED"

    # a pasted link skips the search
    r = client.post("/api/central-banks/FED/fetch", json={"kind": "statement", "url": "https://example.org/s.htm"})
    assert r.json()["resolved_url"] == "https://example.org/s.htm"
    assert client.post("/api/central-banks/FED/fetch", json={"kind": "statement", "url": "ftp://x"}).status_code == 422
    # no automatic projections for the PBOC: a clear message, not a crash
    r = client.post("/api/central-banks/PBOC/fetch", json={"kind": "projections"})
    assert r.status_code == 502 and "paste" in r.json()["detail"].lower()
