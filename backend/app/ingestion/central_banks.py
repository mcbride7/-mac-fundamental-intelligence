"""Central-bank scraper framework: RSS feeds -> statement pages -> stored statements.
Add a bank by adding a FeedSpec; nothing else changes (Section 3)."""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import VerificationStatus
from app.ingestion.base import http_get
from app.models import CentralBankSpeech, CentralBankStatement, Source
from app.services import data_access as da
from app.services.extraction.pipeline import html_to_text, llm_refine_statement_text


@dataclass
class FeedSpec:
    source_key: str
    cb_code: str
    statement_pattern: str  # regex on item title
    speech_pattern: str | None = None
    doc_type: str = "statement"


FEEDS = [
    FeedSpec("fed_rss", "FED", r"(fomc statement|federal reserve issues fomc statement)", None),
    FeedSpec("ecb_rss", "ECB", r"monetary policy decisions", r"speech"),
    FeedSpec("boe_rss", "BOE", r"(monetary policy summary|bank rate (maintained|increased|reduced))", r"speech"),
]


def parse_feed(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        get = {c.tag.split("}")[-1]: c for c in it}
        title = (get.get("title").text or "").strip() if get.get("title") is not None else ""
        link_el = get.get("link")
        link = (link_el.text or link_el.attrib.get("href", "")).strip() if link_el is not None else ""
        # an XML element with no children is falsy, so `a or b` would always skip it
        date_el = next((get[k] for k in ("pubDate", "updated", "published") if k in get), None)
        pub = None
        if date_el is not None and date_el.text:
            try:
                pub = parsedate_to_datetime(date_el.text)
            except (TypeError, ValueError):
                try:
                    pub = datetime.fromisoformat(date_el.text.replace("Z", "+00:00"))
                except ValueError:
                    pub = None
        items.append({"title": title, "link": link, "published": pub})
    return items


def clean_statement(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    # keep from the first sentence that looks like policy text
    m = re.search(r"(Recent indicators|The Governing Council|The Committee|At its meeting|The Monetary Policy "
                  r"Committee|Inflation)", text)
    if m and m.start() < len(text) * 0.6:
        text = text[m.start():]
    cut = re.search(r"(For media inquiries|Implementation Note|Media contacts|Related Information)", text)
    if cut:
        text = text[:cut.start()]
    return text.strip()


def run_feed(db: Session, src: Source, spec: FeedSpec) -> int:
    from app.services import recompute

    cb = da.cb_by_code(db, spec.cb_code)
    items = parse_feed(http_get(src.url).content)
    n = 0
    for it in items:
        title = it["title"]
        is_statement = re.search(spec.statement_pattern, title, re.I)
        is_speech = spec.speech_pattern and re.search(spec.speech_pattern, title, re.I)
        if not (is_statement or is_speech) or not it["link"]:
            continue
        page = http_get(it["link"]).content.decode("utf-8", errors="replace")
        text = clean_statement(html_to_text(page))
        if is_statement:
            text = llm_refine_statement_text(text)
        digest = hashlib.sha256(text.encode()).hexdigest()
        if is_statement:
            if db.scalar(select(CentralBankStatement.id).where(CentralBankStatement.sha256 == digest)):
                continue
            pub = it["published"] or datetime.now(timezone.utc)
            st = CentralBankStatement(central_bank_id=cb.id, doc_type=spec.doc_type, title=title, published_at=pub,
                                      meeting_date=pub.date(), text=text, url=it["link"], source_id=src.id,
                                      sha256=digest, input_method="automated",
                                      verification_status=VerificationStatus.VERIFIED.value)
            db.add(st)
            db.commit()
            recompute.trigger(db, "statement", st.id, central_banks={cb.code}, currencies={cb.currency},
                              statement_ids={st.id})
            n += 1
        else:
            if db.scalar(select(CentralBankSpeech.id).where(CentralBankSpeech.url == it["link"])):
                continue
            speaker = re.split(r"[:–-]", title)[0].strip()[:200]
            db.add(CentralBankSpeech(central_bank_id=cb.id, speaker=speaker, title=title,
                                     delivered_at=it["published"], text=text[:200000], url=it["link"]))
            db.commit()
            n += 1
    return n


def runner(spec: FeedSpec):
    def _fn(db: Session, src: Source) -> int:
        return run_feed(db, src, spec)

    return _fn
