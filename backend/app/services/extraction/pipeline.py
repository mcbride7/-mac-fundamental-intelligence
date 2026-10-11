"""Extraction pipeline (Section 66.3):

    upload/type -> detect type -> extract text (OCR / PDF / HTML / vision LLM)
                -> parse into structured rows -> per-field confidence

Text extraction is deterministic (Tesseract, pdfplumber). If a vision-capable
LLM is configured, screenshots are transcribed by the LLM into a clean table
first, which is usually far more accurate than raw OCR on calendar screenshots.
The LLM output is still parsed by the same deterministic parser and reviewed by
the user, so it can never commit data on its own."""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date

from app.ai.llm import DATA_GUARD, LLMUnavailable, get_llm, wrap_document
from app.services.extraction.text_parser import ParseResult, parse_text

log = logging.getLogger(__name__)

IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/heic", "image/heif", "image/gif"}
PDF_MIMES = {"application/pdf"}

VISION_PROMPT = (
    "Transcribe the economic data visible in this image. If it is a calendar or table, output one line per row "
    "as CSV with header: Time,Currency,Event,Actual,Forecast,Previous (leave a cell empty if not shown). "
    "If it is a central-bank projection table, output the table with a header row of years. If it is prose "
    "(a statement), output the prose verbatim. If it shows rate probabilities, output lines like 'Cut: 20%'. "
    "Output only the transcription — no commentary."
)


@dataclass
class ExtractionOutput:
    text: str
    method: str  # text | ocr | pdf_text | pdf_ocr | vision_llm | html
    ocr_confidence: float  # 0..100 — quality of the text extraction itself
    result: ParseResult
    notes: list[str] = field(default_factory=list)


def _apply_ocr_confidence(result: ParseResult, ocr_conf: float) -> None:
    factor = max(0.3, min(1.0, ocr_conf / 100.0))
    for row in result.rows:
        for k, v in row.confidence.items():
            row.confidence[k] = round(v * factor, 1)


def ocr_image(data: bytes) -> tuple[str, float]:
    """Tesseract OCR with light preprocessing. Returns (text, mean word confidence)."""
    from PIL import Image, ImageOps
    import pytesseract

    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("L")
    if img.width < 1600:
        scale = 1600 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    # dark-mode screenshots: invert so text is dark on light
    from PIL import ImageStat

    if ImageStat.Stat(img).mean[0] < 110:
        img = ImageOps.invert(img)
    data_ = pytesseract.image_to_data(img, config="--psm 6", output_type=pytesseract.Output.DICT)
    confs = [float(c) for c, t in zip(data_["conf"], data_["text"]) if t.strip() and float(c) >= 0]
    text = pytesseract.image_to_string(img, config="--psm 6")
    return text, (sum(confs) / len(confs) if confs else 0.0)


def pdf_text(data: bytes) -> tuple[str, float, str]:
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:40]:
            tables = page.extract_tables() or []
            txt = page.extract_text() or ""
            parts.append(txt)
            for t in tables:
                for row in t:
                    parts.append(" ".join(c or "" for c in row))
    text = "\n".join(p for p in parts if p)
    if len(text.strip()) > 50:
        return text, 97.0, "pdf_text"
    # scanned PDF: render and OCR
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(data)
    texts, confs = [], []
    for i in range(min(len(doc), 10)):
        img = doc[i].render(scale=2.5).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        t, c = ocr_image(buf.getvalue())
        texts.append(t)
        confs.append(c)
    return "\n".join(texts), (sum(confs) / len(confs) if confs else 0.0), "pdf_ocr"


def html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    lines = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if cells:
            lines.append(" ".join(cells))
            tr.decompose()
    body = soup.get_text("\n", strip=True)
    return "\n".join(lines + [body])


def fetch_url(url: str) -> tuple[bytes, str]:
    import requests

    if not re.match(r"^https?://", url):
        raise ValueError("Only http(s) URLs are supported")
    r = requests.get(url, timeout=30, headers={"User-Agent": "MacFundamentalIntelligence/1.0"})
    r.raise_for_status()
    return r.content, r.headers.get("content-type", "").split(";")[0].strip().lower()


def extract_from_text(text: str, today: date | None = None, content_type: str | None = None) -> ExtractionOutput:
    res = parse_text(text, today, content_type)
    return ExtractionOutput(text=text, method="text", ocr_confidence=100.0, result=res)


def extract_from_image(data: bytes, mime: str, today: date | None = None,
                       content_type: str | None = None) -> ExtractionOutput:
    notes: list[str] = []
    llm = get_llm()
    if llm.available:
        try:
            resp = llm.vision(DATA_GUARD, VISION_PROMPT, data, mime if mime != "image/jpg" else "image/jpeg")
            res = parse_text(resp.text, today, content_type)
            if res.rows:
                _apply_ocr_confidence(res, 92.0)
                return ExtractionOutput(resp.text, "vision_llm", 92.0, res, [f"Transcribed by {resp.model}"])
            notes.append("Vision model returned no rows; fell back to OCR")
        except (LLMUnavailable, Exception) as exc:  # network / quota errors
            notes.append(f"Vision model unavailable ({exc.__class__.__name__}); used OCR")
    text, conf = ocr_image(data)
    res = parse_text(text, today, content_type)
    _apply_ocr_confidence(res, conf)
    return ExtractionOutput(text, "ocr", conf, res, notes)


def extract_from_pdf(data: bytes, today: date | None = None, content_type: str | None = None) -> ExtractionOutput:
    text, conf, method = pdf_text(data)
    res = parse_text(text, today, content_type)
    _apply_ocr_confidence(res, conf)
    return ExtractionOutput(text, method, conf, res)


def extract_from_url(url: str, today: date | None = None, content_type: str | None = None) -> ExtractionOutput:
    data, ctype = fetch_url(url)
    if ctype in PDF_MIMES or url.lower().endswith(".pdf"):
        out = extract_from_pdf(data, today, content_type)
    elif ctype in IMAGE_MIMES:
        out = extract_from_image(data, ctype, today, content_type)
    else:
        text = html_to_text(data.decode("utf-8", errors="replace"))
        res = parse_text(text, today, content_type)
        out = ExtractionOutput(text, "html", 95.0, res)
    out.notes.append(f"Fetched {url}")
    return out


def llm_refine_statement_text(text: str) -> str:
    """Optionally ask the LLM to strip page furniture from a statement page."""
    llm = get_llm()
    if not llm.available:
        return text
    try:
        resp = llm.complete(DATA_GUARD, "Return only the body text of the central-bank statement in this "
                                        "document, verbatim, without navigation or footers.\n"
                            + wrap_document(text[:30000]))
        return resp.text.strip() or text
    except Exception:  # pragma: no cover
        return text
