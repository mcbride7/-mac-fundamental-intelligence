"""Press conferences: fetch (Fed, ECB), paste or link a transcript, analyse it and compare it with the
statement and with the previous press conference."""
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
AUTO = {"FED", "ECB"}


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


def fetch(db: Session, cb: CentralBank, day: date | None = None) -> PressConference:
    if cb.code not in AUTO:
        raise ValueError(f"Automatic fetching covers the Fed and ECB; paste the {cb.short_name} transcript or its link instead")
    day = day or cb.last_decision_date or date.today()
    text, url = (fetch_fed if cb.code == "FED" else fetch_ecb)(day)
    return store(db, cb, text, day, f"{cb.short_name} press conference, {day.strftime('%d %b %Y')}", url, "automated")


def from_url(db: Session, cb: CentralBank, url: str, held_on: date, title: str | None = None) -> PressConference:
    from app.services.extraction.pipeline import fetch_url

    content, ctype = fetch_url(url)
    return store(db, cb, _text_from(content, ctype), held_on, title, url, "url")


def run_pressers(db: Session, src: Source) -> int:
    """After a Fed or ECB decision, look for the press conference transcript (published hours later)."""
    from app.services import data_access as da

    n, errors = 0, []
    for code in sorted(AUTO):
        cb = da.cb_by_code(db, code)
        if cb is None or cb.last_decision_date is None:
            continue
        day = cb.last_decision_date
        if (date.today() - day).days > 7:
            continue
        have = db.scalar(select(PressConference.id).where(PressConference.central_bank_id == cb.id,
                                                          PressConference.held_on >= day - timedelta(days=2),
                                                          PressConference.held_on <= day + timedelta(days=2)))
        if have:
            continue
        try:
            fetch(db, cb, day)
            n += 1
        except Exception as exc:
            db.rollback()
            errors.append(f"{code}: {exc}"[:200])
    return (n, "Not found yet: " + "; ".join(errors)) if errors else n


def row(pc: PressConference, full: bool = False) -> dict:
    out = {"id": pc.id, "held_on": pc.held_on.isoformat(), "title": pc.title, "url": pc.url, "tone": pc.tone,
           "label": pa.label(pc.tone), "vs_statement": pc.vs_statement, "questions": pc.questions,
           "input_method": pc.input_method}
    if full:
        out["analysis"] = pc.analysis
        out["text"] = pc.text
    return out
