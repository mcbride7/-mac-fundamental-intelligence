"""Press conferences: fetch them (Fed and ECB transcripts by date; the BoE, BoJ, RBA, BoC, SNB and RBNZ from their
press feeds), or paste / link a transcript; analyse it and compare it with the statement and the previous one."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import presser as pa
from app.ingestion.base import SourceUnavailable, http_get
from app.models import CentralBank, CentralBankStatement, PressConference, Source
from app.services.audit import alert

FED_PDF = "https://www.federalreserve.gov/mediacenter/files/FOMCpresconf{d}.pdf"
ECB_RSS = "https://www.ecb.europa.eu/rss/press.html"
AUTO = {"FED", "ECB"}  # full transcript fetched by date
# every bank whose press feed the News tab already reads: their press conference items are picked up from it
FEED_OF = {"FED": "fed", "ECB": "ecb", "BOE": "boe", "BOJ": "boj", "RBA": "rba", "BOC": "boc", "RBNZ": "rbnz", "SNB": "snb"}
PRESSER_TITLE = re.compile(r"(press conference|media conference|news conference|press briefing|opening statement|"
                           r"opening remarks|introductory remarks|introductory statement|governor'?s? (?:remarks|statement))", re.I)


def _text_from(content: bytes, ctype: str) -> str:
    from app.services.extraction.pipeline import html_to_text, pdf_text

    if "pdf" in ctype or content[:4] == b"%PDF":
        return pdf_text(content)[0]
    return html_to_text(content.decode("utf-8", errors="replace"))


def fetch_fed(day: date) -> tuple[str, str]:
    url = FED_PDF.format(d=day.strftime("%Y%m%d"))
    r = http_get(url, retries=1)
    return _text_from(r.content, r.headers.get("content-type", "")), url


def fetch_ecb(day: date) -> tuple[str, str]:
    from app.ingestion.central_banks import parse_feed

    items = parse_feed(http_get(ECB_RSS, retries=1).content)
    for it in items:
        if not re.search(r"(press conference|monetary policy statement)", it["title"], re.I):
            continue
        pub = it["published"]
        if pub is not None and abs((pub.date() - day).days) > 2:
            continue
        r = http_get(it["link"], retries=1)
        return _text_from(r.content, r.headers.get("content-type", "")), it["link"]
    raise SourceUnavailable(f"No ECB press conference found around {day.isoformat()}")


def _chair_text(text: str) -> str:
    return " ".join(t["text"] for t in pa.split_turns(text) if t["role"] == "chair")


def _statement_near(db: Session, cb: CentralBank, day: date) -> CentralBankStatement | None:
    sts = db.scalars(select(CentralBankStatement).where(CentralBankStatement.central_bank_id == cb.id,
                                                        CentralBankStatement.doc_type == "statement")
                     .order_by(CentralBankStatement.published_at.desc()).limit(6))
    for st in sts:
        d = st.meeting_date or (st.published_at.date() if st.published_at else None)
        if d and abs((d - day).days) <= 3:
            return st
    return None


def store(db: Session, cb: CentralBank, text: str, held_on: date, title: str | None = None, url: str | None = None,
          method: str = "pasted") -> PressConference:
    text = (text or "").strip()
    if len(text) < 200:
        raise ValueError("That transcript is too short to analyse (paste the full press conference)")
    digest = hashlib.sha256(text.encode()).hexdigest()
    old = db.scalar(select(PressConference).where(PressConference.sha256 == digest))
    if old is not None:
        return old
    an = pa.analyse(text)
    tone = an["tone"]
    try:  # AI tone when it is set up, blended with the word list
        from app.engines.cb_engine import blended_tone

        bt = blended_tone(_chair_text(text)[:12000])
        if bt.get("ai") is not None:
            an["tone_method"], an["ai_reasons"] = bt["method"], bt["reasons"]
            tone = round(0.5 * bt["score"] + 0.5 * an["tone"], 1)
    except Exception:
        pass
    an["tone"], an["label"] = tone, pa.label(tone)
    st = _statement_near(db, cb, held_on)
    vs = round(tone - st.tone_score, 1) if st is not None and st.tone_score is not None else None
    an["statement"] = ({"id": st.id, "tone": st.tone_score, "title": st.title} if st is not None else None)
    prev = db.scalar(select(PressConference).where(PressConference.central_bank_id == cb.id,
                                                   PressConference.held_on < held_on)
                     .order_by(PressConference.held_on.desc()))
    if prev is not None:
        an["previous"] = {"id": prev.id, "held_on": prev.held_on.isoformat(), "tone": prev.tone,
                          "shift": round(tone - (prev.tone or 0), 1),
                          **pa.compare_phrases(prev.analysis.get("phrases", []), an["phrases"])}
    pc = PressConference(central_bank_id=cb.id, held_on=held_on, title=title or f"{cb.short_name} press conference",
                         url=url, text=text[:400000], sha256=digest, input_method=method, tone=tone, vs_statement=vs,
                         analysis=an, questions=an["questions"])
    db.add(pc)
    db.commit()
    if vs is not None and abs(vs) >= 15:
        alert(db, "press_conference", f"{cb.short_name} press conference {'more hawkish' if vs > 0 else 'more dovish'} "
              f"than the statement ({vs:+.0f})", f"Press conference tone {tone:+.0f} vs statement {st.tone_score:+.0f}.",
              "MEDIUM", entity="press_conference", entity_id=pc.id, currency=cb.currency, central_bank_code=cb.code)
    return pc


def feed_items(db: Session, cb: CentralBank, days: int = 10) -> list[dict]:
    """Press-conference items from the bank's press feed: from the News tab's stored headlines, or the feed itself."""
    from app.models import NewsArticle
    from app.services import news

    key = FEED_OF.get(cb.code)
    if key is None:
        return []
    since = datetime.now(timezone.utc) - timedelta(days=days)
    items = [{"title": a.title, "link": a.url, "published": a.published_at}
             for a in db.scalars(select(NewsArticle).where(NewsArticle.feed == key, NewsArticle.published_at >= since))]
    if not items:
        url = next((u for k, _, u, _, _ in news.RSS_FEEDS if k == key), None)
        if url:
            items = news.fetch_rss(url)
    out = []
    for it in items:
        pub = it.get("published")
        if pub is not None and pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if it.get("link") and PRESSER_TITLE.search(it["title"] or "") and (pub is None or pub >= since):
            out.append({**it, "published": pub})
    return sorted(out, key=lambda x: x["published"] or since, reverse=True)


def fetch_from_feed(db: Session, cb: CentralBank) -> list[PressConference]:
    got = []
    for it in feed_items(db, cb):
        if db.scalar(select(PressConference.id).where(PressConference.url == it["link"])):
            continue
        r = http_get(it["link"], retries=1)
        text = _text_from(r.content, r.headers.get("content-type", ""))
        day = (it["published"] or datetime.now(timezone.utc)).date()
        try:
            got.append(store(db, cb, text, day, it["title"][:300], it["link"], "automated"))
        except ValueError:  # page too short to be a transcript (e.g. just a video link)
            continue
    return got


def fetch(db: Session, cb: CentralBank, day: date | None = None) -> PressConference:
    if cb.code in AUTO:
        day = day or cb.last_decision_date or date.today()
        try:
            text, url = (fetch_fed if cb.code == "FED" else fetch_ecb)(day)
            return store(db, cb, text, day, f"{cb.short_name} press conference, {day.strftime('%d %b %Y')}", url, "automated")
        except SourceUnavailable:
            pass  # fall back to the press feed below
    if cb.code not in FEED_OF:
        raise ValueError(f"The app doesn't read a press feed for the {cb.short_name}: paste the transcript or its link instead")
    got = fetch_from_feed(db, cb)
    if got:
        return got[0]
    latest = db.scalar(select(PressConference).where(PressConference.central_bank_id == cb.id)
                       .order_by(PressConference.held_on.desc()))
    if latest is not None and (date.today() - latest.held_on).days <= 10:
        return latest
    raise SourceUnavailable(f"No {cb.short_name} press conference or opening statement found in its press feed in the "
                            "last 10 days. If it was video only, paste a transcript (e.g. from YouTube).")


def from_url(db: Session, cb: CentralBank, url: str, held_on: date, title: str | None = None) -> PressConference:
    from app.services.extraction.pipeline import fetch_url

    content, ctype = fetch_url(url)
    return store(db, cb, _text_from(content, ctype), held_on, title, url, "url")


def run_pressers(db: Session, src: Source) -> int:
    """After each decision: Fed and ECB full transcripts by date, and every bank's press feed for press-conference,
    media-conference, opening-statement or introductory-remarks items."""
    from app.services import data_access as da

    n, errors = 0, []
    for code in sorted(AUTO):
        cb = da.cb_by_code(db, code)
        if cb is None or cb.last_decision_date is None or (date.today() - cb.last_decision_date).days > 7:
            continue
        day = cb.last_decision_date
        have = db.scalar(select(PressConference.id).where(PressConference.central_bank_id == cb.id,
                                                          PressConference.held_on >= day - timedelta(days=2),
                                                          PressConference.held_on <= day + timedelta(days=2)))
        if have:
            continue
        try:
            text, url = (fetch_fed if code == "FED" else fetch_ecb)(day)
            store(db, cb, text, day, f"{cb.short_name} press conference, {day.strftime('%d %b %Y')}", url, "automated")
            n += 1
        except Exception as exc:
            db.rollback()
            errors.append(f"{code}: {exc}"[:160])
    for code in FEED_OF:
        cb = da.cb_by_code(db, code)
        if cb is None:
            continue
        try:
            n += len(fetch_from_feed(db, cb))
        except Exception as exc:
            db.rollback()
            errors.append(f"{code} feed: {exc}"[:160])
    return (n, "Not found yet: " + "; ".join(errors)) if errors else n


def row(pc: PressConference, full: bool = False) -> dict:
    out = {"id": pc.id, "held_on": pc.held_on.isoformat(), "title": pc.title, "url": pc.url, "tone": pc.tone,
           "label": pa.label(pc.tone), "vs_statement": pc.vs_statement, "questions": pc.questions,
           "input_method": pc.input_method}
    if full:
        out["analysis"] = pc.analysis
        out["text"] = pc.text
    return out
