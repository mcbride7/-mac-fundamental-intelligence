"""Manual data ingestion (Section 66): submissions, extraction, review, commit.

Flow:
    submit_text / submit_file / submit_url
        -> extraction pipeline -> ExtractedDataPoint rows (pending, with
           mapping, per-field confidence, missing fields and validation warnings)
    update_point   (user edits a field on the review screen; re-validated)
    commit         (user confirms; entities created as UNVERIFIED or
                    USER_CONFIRMED; full re-analysis triggered)
    discard / delete_upload
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ConfirmationBasis, InputMethod, VerificationStatus
from app.db import utcnow
from app.models import (
    BondYield,
    CentralBankProjection,
    CentralBankStatement,
    DataConfirmation,
    DataReconciliation,
    EconomicEvent,
    EconomicForecast,
    EconomicRelease,
    ExtractedDataPoint,
    ExtractionReview,
    Indicator,
    ManualSubmission,
    ManualSubmissionFile,
    MarketPrice,
    ProjectionVintage,
    RateExpectation,
    Source,
    UserTrustSettings,
)
from app.services import data_access as da
from app.services import storage
from app.services.audit import alert, audit
from app.services.extraction import pipeline
from app.services.extraction.normalizer import convert_unit, map_indicator
from app.services.extraction.text_parser import COUNTRY_OF_CCY, CURRENCY_OF
from app.services.validation import validate_release

OFFICIAL_NAMES = {
    "bls": "BLS", "bureau of labor statistics": "BLS", "bea": "BEA", "bureau of economic analysis": "BEA",
    "eurostat": "Eurostat", "ons": "ONS", "office for national statistics": "ONS", "stats sa": "Stats SA",
    "statistics south africa": "Stats SA", "federal reserve": "Federal Reserve", "fomc": "Federal Reserve",
    "european central bank": "ECB", "bank of england": "Bank of England", "bank of japan": "Bank of Japan",
    "statistics canada": "Statistics Canada", "abs": "ABS", "australian bureau of statistics": "ABS",
    "stats nz": "Stats NZ", "inegi": "INEGI", "south african reserve bank": "SARB", "resbank": "SARB",
}

CB_PATTERNS = [
    ("FED", r"\b(federal reserve|fomc|federal open market committee|federal funds|fed)\b"),
    ("ECB", r"\b(european central bank|ecb|governing council|eurosystem)\b"),
    ("BOE", r"\b(bank of england|monetary policy committee|boe|bank rate)\b"),
    ("BOJ", r"\b(bank of japan|boj)\b"),
    ("SNB", r"\b(swiss national bank|snb)\b"),
    ("BOC", r"\b(bank of canada|boc)\b"),
    ("RBA", r"\b(reserve bank of australia|rba|cash rate)\b"),
    ("RBNZ", r"\b(reserve bank of new zealand|rbnz|official cash rate)\b"),
    ("SARB", r"\b(south african reserve bank|sarb|repurchase rate|repo rate)\b"),
    ("PBOC", r"\b(people's bank of china|pboc|loan prime rate)\b"),
    ("BANXICO", r"\b(banco de m[eé]xico|banxico|bank of mexico)\b"),
]

METHOD_BY_MIME = {"application/pdf": InputMethod.PDF.value}


class CommitBlocked(ValueError):
    def __init__(self, problems: list[dict]):
        super().__init__("Some rows have errors that need a correction or an override reason")
        self.problems = problems


# ---------------------------------------------------------------------------
# detection helpers
# ---------------------------------------------------------------------------

def detect_central_bank(text: str) -> str | None:
    low = text.lower()
    best, best_hits = None, 0
    for code, pat in CB_PATTERNS:
        hits = len(re.findall(pat, low))
        if hits > best_hits:
            best, best_hits = code, hits
    return best


def detect_source_name(text: str) -> str | None:
    low = text.lower()
    m = re.search(r"source[s]?\s*[:\-]\s*([^\n]{2,60})", low)
    scope = m.group(1) if m else low
    for k in sorted(OFFICIAL_NAMES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(k)}\b", scope):
            return OFFICIAL_NAMES[k]
    return m.group(1).strip().title() if m else None


def detect_date(text: str) -> date | None:
    from app.services.extraction.text_parser import MONTHS

    low = text.lower()
    m = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", low)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = re.search(r"\b(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(\d{1,2}),?\s+(20\d{2})\b",
                  low)
    if m:
        try:
            return date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2)))
        except ValueError:
            pass
    m = re.search(r"\b(\d{1,2})\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?\s+(20\d{2})\b",
                  low)
    if m:
        try:
            return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
        except ValueError:
            pass
    return None


def _official_tier_name(name: str | None) -> bool:
    return bool(name) and name in set(OFFICIAL_NAMES.values())


# ---------------------------------------------------------------------------
# building review rows
# ---------------------------------------------------------------------------

REQUIRED = {
    "economic_release": ["indicator_code", "reference_period", "actual"],
    "cb_projection": ["central_bank_code", "variable", "target_period", "value"],
    "cb_statement": ["central_bank_code", "text"],
    "speech": ["central_bank_code", "text"],
    "rate_expectation": ["central_bank_code", "prob_cut", "prob_hold", "prob_hike"],
    "market_price": ["symbol", "price"],
    "bond_yield": ["country", "tenor", "yield_pct"],
}


def _validate_point(db: Session, p: ExtractedDataPoint, related: dict[str, float] | None = None) -> None:
    f = dict(p.fields)
    warnings: list[dict] = []
    if p.kind == "economic_release":
        ind = da.indicator_by_code(db, f["indicator_code"]) if f.get("indicator_code") else None
        if ind is None and f.get("indicator_text"):
            code, conf, cands = map_indicator(f.get("indicator_text", ""), f.get("country"), f.get("transform"),
                                              da.indicator_refs(db))
            p.mapping_confidence = conf
            f["candidates"] = cands
            if code:
                f["indicator_code"] = code
                ind = da.indicator_by_code(db, code)
        if ind is not None:
            f.setdefault("country", ind.country)
            f.setdefault("currency", ind.currency)
            for k in ("actual", "previous", "consensus"):
                if isinstance(f.get(k), (int, float)):
                    val, note = convert_unit(float(f[k]), f.get("unit"), ind.unit)
                    if note and val != f[k]:
                        f[k] = round(val, 6)
                        warnings.append({"code": "UNIT_CONVERTED", "message": note, "severity": "info"})
            hist = [r.actual for r in da.current_series(db, ind.id, 36)
                    if r.reference_period != f.get("reference_period")]
            existing = [{"id": r.id, "actual": r.actual, "verification_status": r.verification_status}
                        for r in da.releases_for_period(db, ind.id, f.get("reference_period") or "")
                        if r.is_current]
            released_at = _released_at(f)
            warnings += validate_release(
                indicator_code=ind.code, indicator_unit=ind.unit, indicator_transform=ind.transform,
                indicator_frequency=ind.frequency, actual=_num(f.get("actual")), previous=_num(f.get("previous")),
                consensus=_num(f.get("consensus")), reference_period=f.get("reference_period"),
                released_at=released_at, history=hist, existing_same_period=existing,
                parsed_transform=f.get("transform"),
                parsed_unit=f.get("unit") if f.get("unit") not in ("k", "m", "bn") else None,
                related_values=related or {},
            )
        else:
            warnings += validate_release(
                indicator_code=None, indicator_unit=None, indicator_transform=None, indicator_frequency=None,
                actual=_num(f.get("actual")), previous=_num(f.get("previous")), consensus=_num(f.get("consensus")),
                reference_period=f.get("reference_period"), released_at=None, history=[], existing_same_period=[])
    elif p.kind == "rate_expectation":
        tot = sum(_num(f.get(k)) or 0 for k in ("prob_cut", "prob_hold", "prob_hike"))
        if abs(tot - 100) > 2:
            warnings.append({"code": "PROB_SUM", "message": f"Probabilities sum to {tot:.1f}%",
                             "severity": "warning"})
    p.fields = f
    p.indicator_code = f.get("indicator_code")
    p.missing_fields = [k for k in REQUIRED.get(p.kind, []) if f.get(k) in (None, "")]
    for k in p.missing_fields:
        if not any(w["code"].startswith("MISSING") and k in w["message"].lower() for w in warnings):
            warnings.append({"code": "MISSING_FIELD", "message": f"Missing {k.replace('_', ' ')}",
                             "severity": "error"})
    # de-duplicate
    seen, uniq = set(), []
    for w in warnings:
        key = (w["code"], w["message"])
        if key not in seen:
            seen.add(key)
            uniq.append(w)
    p.warnings = uniq


def _num(v) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _released_at(f: dict) -> datetime | None:
    d = f.get("release_date")
    if not d:
        return None
    try:
        dd = date.fromisoformat(str(d)[:10])
    except ValueError:
        return None
    t = time(0, 0)
    if f.get("release_time"):
        try:
            hh, mm = str(f["release_time"]).split(":")[:2]
            t = time(int(hh), int(mm))
        except ValueError:
            pass
    return datetime.combine(dd, t, tzinfo=timezone.utc)


def _build_points(db: Session, sub: ManualSubmission, out: pipeline.ExtractionOutput) -> None:
    sub.content_type = out.result.content_type
    sub.content_type_confidence = out.result.content_type_confidence
    sub.raw_text = out.text[:200_000]
    hint = sub.hint or {}
    full_text = out.text
    src_name = detect_source_name(full_text)
    cb_code = hint.get("central_bank_code") or detect_central_bank(full_text)
    doc_date = detect_date(full_text)
    country_hint = hint.get("country")
    rows_by_index: list[ExtractedDataPoint] = []
    for i, row in enumerate(out.result.rows):
        fields = dict(row.fields)
        conf = dict(row.confidence)
        kind = row.kind
        if kind == "economic_release":
            if hint.get("indicator_code") and len(out.result.rows) == 1:
                fields["indicator_code"] = hint["indicator_code"]
                conf["indicator_code"] = 100.0
            if country_hint and not fields.get("country"):
                fields["country"] = country_hint
                fields["currency"] = CURRENCY_OF.get(country_hint)
            if hint.get("reference_period") and not fields.get("reference_period"):
                fields["reference_period"] = hint["reference_period"]
                conf["reference_period"] = 100.0
            if not fields.get("country") and fields.get("currency"):
                fields["country"] = COUNTRY_OF_CCY.get(fields["currency"])
            if hint.get("release_date") and not fields.get("release_date"):
                fields["release_date"] = hint["release_date"]
            if src_name:
                fields.setdefault("source_name", src_name)
        elif kind in ("cb_projection", "cb_statement", "speech", "rate_expectation"):
            fields.setdefault("central_bank_code", cb_code)
            conf.setdefault("central_bank_code", 100.0 if hint.get("central_bank_code") else (70.0 if cb_code else 0))
            if kind == "cb_projection":
                fields.setdefault("vintage_date", (hint.get("vintage_date") or (doc_date or date.today()).isoformat()))
                conf.setdefault("vintage_date", 100.0 if hint.get("vintage_date") else (75.0 if doc_date else 30.0))
            if kind in ("cb_statement", "speech"):
                fields.setdefault("published_date", hint.get("published_date") or (doc_date.isoformat()
                                                                                  if doc_date else None))
                fields.setdefault("doc_type", hint.get("doc_type", "statement"))
        p = ExtractedDataPoint(submission_id=sub.id, row_index=i, kind=kind, fields=fields,
                               field_confidence=conf, warnings=list(row.warnings and [
                                   {"code": "PARSER", "message": w, "severity": "warning"} for w in row.warnings]))
        rows_by_index.append(p)
    # related values for headline/core consistency checks
    related = {}
    for p in rows_by_index:
        if p.kind == "economic_release":
            _validate_point(db, p)
            if p.fields.get("indicator_code") and _num(p.fields.get("actual")) is not None:
                related[p.fields["indicator_code"]] = _num(p.fields["actual"])
    for p in rows_by_index:
        if p.kind == "economic_release":
            parser_w = [w for w in p.warnings if w["code"] == "PARSER"]
            _validate_point(db, p, related)
            p.warnings = parser_w + [w for w in p.warnings if w["code"] != "PARSER"]
        else:
            parser_w = list(p.warnings)
            _validate_point(db, p)
            p.warnings = parser_w + p.warnings
        db.add(p)
    if not rows_by_index:
        sub.status = "failed"
        sub.error = "No data could be extracted. Try typing the values, or add a hint (indicator / period)."
    db.commit()


def _new_submission(db: Session, method: str, user_id: int | None, hint: dict | None,
                    url: str | None = None) -> ManualSubmission:
    sub = ManualSubmission(user_id=user_id, input_method=method, hint=hint or {}, url=url)
    db.add(sub)
    db.flush()
    return sub


def submit_text(db: Session, text: str, user_id: int | None = None, hint: dict | None = None,
                input_method: str = InputMethod.TYPED.value, content_type: str | None = None) -> ManualSubmission:
    method = InputMethod.CSV.value if (input_method == InputMethod.TYPED.value and _looks_csv(text)) else input_method
    sub = _new_submission(db, method, user_id, hint)
    out = pipeline.extract_from_text(text, content_type=content_type)
    _build_points(db, sub, out)
    audit(db, "manual_submission", sub.id, "submitted", user_id, method=method, chars=len(text))
    db.commit()
    return sub


def _looks_csv(text: str) -> bool:
    first = text.strip().split("\n", 1)[0].lower()
    return ("," in first or "\t" in first) and bool(re.search(r"indicator|event|actual", first))


def submit_file(db: Session, data: bytes, filename: str, mime: str, user_id: int | None = None,
                hint: dict | None = None, input_method: str | None = None,
                content_type: str | None = None) -> ManualSubmission:
    mime = (mime or "").lower()
    if mime in ("text/plain", "text/csv"):
        return submit_text(db, data.decode("utf-8", errors="replace"), user_id, hint,
                           InputMethod.CSV.value if mime == "text/csv" else InputMethod.TYPED.value, content_type)
    storage.check_upload(data, mime)
    digest, uri = storage.store(data, filename)
    method = input_method or METHOD_BY_MIME.get(mime, InputMethod.SCREENSHOT.value)
    sub = _new_submission(db, method, user_id, hint)
    db.add(ManualSubmissionFile(submission_id=sub.id, filename=filename[:300], mime_type=mime,
                                size_bytes=len(data), sha256=digest, storage_path=uri))
    try:
        if mime == "application/pdf":
            out = pipeline.extract_from_pdf(data, content_type=content_type)
        else:
            out = pipeline.extract_from_image(data, mime, content_type=content_type)
        _build_points(db, sub, out)
        sub.hint = {**(sub.hint or {}), "_notes": out.notes, "_method": out.method,
                    "_ocr_confidence": round(out.ocr_confidence, 1)}
    except Exception as exc:
        sub.status = "failed"
        sub.error = f"Extraction failed: {exc}. You can type the values instead."
    audit(db, "manual_submission", sub.id, "submitted", user_id, method=method, sha256=digest, filename=filename)
    db.commit()
    return sub


def submit_url(db: Session, url: str, user_id: int | None = None, hint: dict | None = None,
               content_type: str | None = None) -> ManualSubmission:
    sub = _new_submission(db, InputMethod.URL.value, user_id, hint, url=url)
    try:
        out = pipeline.extract_from_url(url, content_type=content_type)
        _build_points(db, sub, out)
    except Exception as exc:
        sub.status = "failed"
        sub.error = f"Could not fetch or parse the URL ({exc}). Take a screenshot or paste the text instead."
    audit(db, "manual_submission", sub.id, "submitted", user_id, method="url", url=url)
    db.commit()
    return sub


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------

def serialize_point(p: ExtractedDataPoint) -> dict:
    return {
        "id": p.id, "row_index": p.row_index, "kind": p.kind, "fields": p.fields,
        "field_confidence": p.field_confidence, "indicator_code": p.indicator_code,
        "mapping_confidence": p.mapping_confidence, "warnings": p.warnings, "missing_fields": p.missing_fields,
        "status": p.status, "committed_entity": p.committed_entity, "committed_id": p.committed_id,
        "low_confidence_fields": [k for k, v in (p.field_confidence or {}).items() if v < 70],
        "has_errors": any(w.get("severity") == "error" for w in p.warnings or []),
    }


def serialize_submission(db: Session, sub: ManualSubmission) -> dict:
    files = list(db.scalars(select(ManualSubmissionFile).where(ManualSubmissionFile.submission_id == sub.id)))
    points = list(db.scalars(select(ExtractedDataPoint).where(ExtractedDataPoint.submission_id == sub.id)
                             .order_by(ExtractedDataPoint.row_index)))
    hint = dict(sub.hint or {})
    return {
        "id": sub.id, "input_method": sub.input_method, "content_type": sub.content_type,
        "content_type_confidence": sub.content_type_confidence, "status": sub.status, "error": sub.error,
        "url": sub.url, "created_at": sub.created_at, "raw_text": (sub.raw_text or "")[:20000],
        "extraction_method": hint.pop("_method", "text"), "ocr_confidence": hint.pop("_ocr_confidence", None),
        "notes": hint.pop("_notes", []), "hint": hint,
        "files": [{"id": f.id, "filename": f.filename, "mime_type": f.mime_type, "size_bytes": f.size_bytes,
                   "sha256": f.sha256} for f in files],
        "points": [serialize_point(p) for p in points],
        "source_removed": sub.source_removed,
    }


def update_point(db: Session, point_id: int, fields: dict, user_id: int | None = None) -> ExtractedDataPoint:
    p = db.get(ExtractedDataPoint, point_id)
    if p is None:
        raise LookupError("Data point not found")
    if p.status != "pending":
        raise ValueError("Only pending rows can be edited")
    before = dict(p.fields)
    new = {**p.fields, **fields}
    if "indicator_code" in fields:
        new.pop("candidates", None)
    conf = dict(p.field_confidence or {})
    for k in fields:
        conf[k] = 100.0  # human-entered
    p.fields, p.field_confidence = new, conf
    _validate_point(db, p)
    db.add(ExtractionReview(data_point_id=p.id, user_id=user_id, action="edit",
                            changes={k: {"from": before.get(k), "to": v} for k, v in fields.items()}))
    db.commit()
    return p


def discard(db: Session, sub_id: int, user_id: int | None = None) -> ManualSubmission:
    sub = db.get(ManualSubmission, sub_id)
    if sub is None:
        raise LookupError("Submission not found")
    for p in db.scalars(select(ExtractedDataPoint).where(ExtractedDataPoint.submission_id == sub_id,
                                                         ExtractedDataPoint.status == "pending")):
        p.status = "discarded"
        db.add(ExtractionReview(data_point_id=p.id, user_id=user_id, action="discard"))
    sub.status = "discarded" if sub.status != "committed" else sub.status
    audit(db, "manual_submission", sub_id, "discarded", user_id)
    db.commit()
    return sub


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------

def _trust(db: Session, user_id: int | None) -> UserTrustSettings | None:
    return db.get(UserTrustSettings, user_id) if user_id else None


def _auto_confirm_basis(sub: ManualSubmission, p: ExtractedDataPoint, trust: UserTrustSettings | None
                        ) -> str | None:
    if trust is None:
        return None
    src = p.fields.get("source_name")
    if src and src in (trust.trusted_sources or []):
        return (ConfirmationBasis.OFFICIAL_SOURCE.value if _official_tier_name(src)
                else ConfirmationBasis.SECONDARY_SOURCE.value)
    if sub.input_method in (InputMethod.TYPED.value, InputMethod.CSV.value) and trust.auto_confirm_typed:
        return ConfirmationBasis.NO_SOURCE.value
    if sub.input_method in (InputMethod.SCREENSHOT.value, InputMethod.PHOTO.value, InputMethod.PDF.value) \
            and trust.auto_confirm_official_screenshots and _official_tier_name(src):
        confs = [v for k, v in (p.field_confidence or {}).items() if k in ("actual", "indicator_code",
                                                                             "indicator_text", "reference_period")]
        if confs and min(confs) >= trust.auto_confirm_threshold:
            return ConfirmationBasis.OFFICIAL_SOURCE.value
    return None


def _commit_release(db: Session, sub: ManualSubmission, p: ExtractedDataPoint, user_id: int | None,
                    confirm: dict | None, trust) -> tuple[EconomicRelease, list[str]]:
    f = p.fields
    ind = da.indicator_by_code(db, f["indicator_code"])
    if ind is None:
        raise ValueError(f"Unknown indicator {f['indicator_code']}")
    period = f["reference_period"]
    notes: list[str] = []
    actual = float(f["actual"])
    prev = _num(f.get("previous"))
    cons = _num(f.get("consensus"))
    released_at = _released_at(f) or utcnow()
    ev = da.event_for(db, ind.id, period)
    if ev is None:
        ev = EconomicEvent(indicator_id=ind.id, reference_period=period, scheduled_at=released_at,
                           importance=ind.importance, previous=prev, consensus=cons,
                           consensus_source="manual" if cons is not None else None)
        db.add(ev)
        db.flush()
    else:
        if ev.previous is None and prev is not None:
            ev.previous = prev
        if cons is not None and ev.consensus is None:
            ev.consensus, ev.consensus_source = cons, "manual"
    if cons is not None:
        db.add(EconomicForecast(event_id=ev.id, forecaster="market", value=cons,
                                source_name=f.get("consensus_source") or "manual", input_method=sub.input_method))
    cur = da.current_release(db, ind.id, period)
    all_rows = da.releases_for_period(db, ind.id, period)
    if cur is not None and abs(cur.actual - actual) < 1e-9:
        notes.append(f"Value already stored (release #{cur.id}); no duplicate created")
        return cur, notes
    actual_conf = (p.field_confidence or {}).get("actual")
    rel = EconomicRelease(
        event_id=ev.id, indicator_id=ind.id, reference_period=period, actual=actual,
        previous=prev if prev is not None else ev.previous, consensus=cons if cons is not None else ev.consensus,
        unit=ind.unit, released_at=released_at,
        revision_number=_revision_number(cur, all_rows, bool(f.get("is_revision"))),
        source_name=f.get("source_name"), source_url=sub.url, input_method=sub.input_method,
        verification_status=VerificationStatus.UNVERIFIED.value,
        extraction_confidence=None if sub.input_method in (InputMethod.TYPED.value, InputMethod.CSV.value)
        else actual_conf, submission_id=sub.id, created_by=user_id,
    )
    manual_src = db.scalar(select(Source).where(Source.key == "manual"))
    rel.source_id = manual_src.id if manual_src else None
    db.add(rel)
    db.flush()
    if cur is not None:
        if cur.verification_status == VerificationStatus.VERIFIED.value and not f.get("is_revision"):
            # differs from official data: keep both, never overwrite (Section 51)
            rel.is_current = False
            rel.verification_status = VerificationStatus.CONFLICT.value
            db.add(DataReconciliation(release_id=rel.id, official_release_id=cur.id, manual_value=actual,
                                      official_value=cur.actual, official_source=cur.source_name,
                                      prior_status=VerificationStatus.UNVERIFIED.value))
            alert(db, "data_conflict", f"{ind.name} {period}: manual value differs from official data",
                  f"You entered {actual}; the official source has {cur.actual}. Both are kept. "
                  "Review on the Data Health page.", "HIGH", entity="economic_release", entity_id=rel.id,
                  currency=ind.currency)
            notes.append("Differs from verified official value — stored as CONFLICT for review")
            return rel, notes
        cur.is_current = False
        cur.verification_status = VerificationStatus.SUPERSEDED.value
        cur.superseded_by_id = rel.id
        notes.append(f"Supersedes release #{cur.id} ({cur.actual})")
    basis = None
    auto = False
    if confirm and confirm.get("basis"):
        basis = confirm["basis"]
    else:
        basis = _auto_confirm_basis(sub, p, trust)
        auto = basis is not None
    if basis:
        rel.verification_status = VerificationStatus.USER_CONFIRMED.value
        rel.confirmation_basis = basis
        db.add(DataConfirmation(release_id=rel.id, user_id=user_id, basis=basis,
                                source_name=(confirm or {}).get("source_name") or f.get("source_name"),
                                source_url=(confirm or {}).get("source_url"), note=(confirm or {}).get("note"),
                                auto=auto))
        notes.append(("Auto-confirmed" if auto else "Confirmed") + f" ({basis.lower().replace('_', ' ')})")
    return rel, notes


def _revision_number(cur: EconomicRelease | None, all_rows: list[EconomicRelease], is_revision: bool) -> int:
    if not all_rows:
        return 0
    if cur is not None and cur.input_method != "automated" and not is_revision:
        return cur.revision_number  # correction of a manual entry, same print
    if cur is not None and cur.verification_status == VerificationStatus.VERIFIED.value and not is_revision:
        return cur.revision_number  # competing value for the same print (conflict)
    return max(r.revision_number for r in all_rows) + 1


def commit(db: Session, sub_id: int, user_id: int | None = None, rows: list[dict] | None = None,
           confirm: dict | None = None, run_recompute: bool = True) -> dict:
    """Commit reviewed rows. `rows` = [{"id": point_id, "fields": {...}, "override_reason": str, "include": bool}]
    (omit to commit every pending row). `confirm` = {"basis", "source_name", "source_url", "note"} marks the
    committed releases USER_CONFIRMED immediately."""
    from app.services import recompute

    sub = db.get(ManualSubmission, sub_id)
    if sub is None:
        raise LookupError("Submission not found")
    points = {p.id: p for p in db.scalars(select(ExtractedDataPoint).where(
        ExtractedDataPoint.submission_id == sub_id, ExtractedDataPoint.status == "pending"))}
    selected: list[tuple[ExtractedDataPoint, str | None]] = []
    if rows is None:
        selected = [(p, None) for p in points.values()]
    else:
        for r in rows:
            p = points.get(r["id"])
            if p is None or r.get("include") is False:
                continue
            if r.get("fields"):
                update_point(db, p.id, r["fields"], user_id)
            selected.append((p, r.get("override_reason")))
    # Save what can be saved instead of blocking the whole upload:
    # - rows that are fine (or overridden with a reason) are committed,
    # - calendar rows with a forecast/previous but no actual yet are filed as upcoming events,
    # - everything else is skipped and reported back so the user can fix and re-add it.
    problems, upcoming, ready = [], [], []
    for p, reason in selected:
        errors = [w for w in p.warnings or [] if w.get("severity") == "error"]
        codes = {w["code"] for w in errors}
        f = p.fields
        is_upcoming = (p.kind == "economic_release" and _num(f.get("actual")) is None
                       and da.indicator_by_code(db, f.get("indicator_code") or "") is not None
                       and bool(f.get("reference_period"))
                       and codes <= {"MISSING_ACTUAL", "MISSING_FIELD"}
                       and (_num(f.get("consensus")) is not None or _num(f.get("previous")) is not None))
        if is_upcoming:
            upcoming.append(p)
            continue
        hard = [w for w in errors if w["code"] in ("MISSING_FIELD", "UNMAPPED_INDICATOR", "MISSING_ACTUAL",
                                                   "MISSING_PERIOD")]
        if hard or (errors and not reason):
            problems.append({"id": p.id, "row_index": p.row_index, "errors": errors,
                             "label": f.get("indicator_text") or f.get("indicator_code") or p.kind,
                             "needs": "correction" if hard else "override_reason"})
            continue
        ready.append((p, reason))
    if not ready and not upcoming:
        if problems:
            raise CommitBlocked(problems)
        raise ValueError("Nothing to commit")
    selected = ready
    trust = _trust(db, user_id)
    committed: list[dict] = []
    for p in upcoming:
        f = p.fields
        ind = da.indicator_by_code(db, f["indicator_code"])
        ev = da.event_for(db, ind.id, f["reference_period"])
        if ev is None:
            ev = EconomicEvent(indicator_id=ind.id, reference_period=f["reference_period"],
                               importance=ind.importance)
            db.add(ev)
            db.flush()
        ev.scheduled_at = _released_at(f) or ev.scheduled_at
        if _num(f.get("consensus")) is not None:
            ev.consensus, ev.consensus_source = _num(f.get("consensus")), "manual"
        if _num(f.get("previous")) is not None:
            ev.previous = _num(f.get("previous"))
        p.status, p.committed_entity, p.committed_id = "committed", "economic_event", ev.id
        db.add(ExtractionReview(data_point_id=p.id, user_id=user_id, action="confirm"))
        committed.append({"point_id": p.id, "entity": "economic_event", "id": ev.id,
                          "notes": [f"{ind.name} {f['reference_period']}: saved to the calendar as upcoming "
                                    "(forecast/previous). Add the actual after the release."]})
    triggers: dict[str, dict] = defaultdict(lambda: defaultdict(set))
    projections_by_vintage: dict[tuple, list[ExtractedDataPoint]] = defaultdict(list)
    for p, reason in selected:
        f = p.fields
        entity, eid, notes = None, None, []
        if p.kind == "economic_release":
            rel, notes = _commit_release(db, sub, p, user_id, confirm, trust)
            entity, eid = "economic_release", rel.id
            ind = db.get(Indicator, rel.indicator_id)
            t = triggers["release"]
            t["release_ids"].add(rel.id)
            t["indicator_ids"].add(ind.id)
            t["currencies"].add(ind.currency)
            if ind.central_bank_code:
                t["central_banks"].add(ind.central_bank_code)
        elif p.kind == "cb_projection":
            projections_by_vintage[(f["central_bank_code"], f.get("vintage_date"))].append(p)
            continue
        elif p.kind in ("cb_statement", "speech"):
            cb = da.cb_by_code(db, f["central_bank_code"])
            if cb is None:
                raise ValueError(f"Unknown central bank {f['central_bank_code']}")
            pub = f.get("published_date")
            pub_dt = datetime.combine(date.fromisoformat(pub), time(12), tzinfo=timezone.utc) if pub else utcnow()
            st = CentralBankStatement(central_bank_id=cb.id, doc_type=f.get("doc_type", "statement"),
                                      title=f.get("title") or f"{cb.short_name} {f.get('doc_type', 'statement')}",
                                      published_at=pub_dt, meeting_date=pub_dt.date(), text=f["text"],
                                      url=sub.url, sha256=storage.sha256(f["text"].encode()),
                                      input_method=sub.input_method,
                                      verification_status=VerificationStatus.UNVERIFIED.value)
            db.add(st)
            db.flush()
            entity, eid = "cb_statement", st.id
            t = triggers["statement"]
            t["central_banks"].add(cb.code)
            t["currencies"].add(cb.currency)
            t["statement_ids"].add(st.id)
        elif p.kind == "rate_expectation":
            cb = da.cb_by_code(db, f["central_bank_code"])
            re_ = RateExpectation(central_bank_code=f["central_bank_code"], ts=utcnow(),
                                  meeting_date=f.get("meeting_date"), prob_cut=_num(f.get("prob_cut")) or 0,
                                  prob_hold=_num(f.get("prob_hold")) or 0, prob_hike=_num(f.get("prob_hike")) or 0,
                                  source=f.get("source_name") or "manual", input_method=sub.input_method)
            db.add(re_)
            entity = "rate_expectation"
            t = triggers["rate_expectation"]
            t["central_banks"].add(f["central_bank_code"])
            if cb:
                t["currencies"].add(cb.currency)
        elif p.kind == "market_price":
            db.add(MarketPrice(symbol=f["symbol"], ts=utcnow(), price=float(f["price"]),
                               asset_class=f.get("asset_class", "fx"), source="manual",
                               input_method=sub.input_method,
                               verification_status=VerificationStatus.UNVERIFIED.value))
            entity = "market_price"
            triggers["market_data"]["symbols"].add(f["symbol"])
        elif p.kind == "bond_yield":
            db.add(BondYield(country=f["country"], tenor=f["tenor"], ts=utcnow(), yield_pct=float(f["yield_pct"]),
                             source="manual", input_method=sub.input_method))
            entity = "bond_yield"
            triggers["market_data"]["countries"].add(f["country"])
        p.status, p.committed_entity, p.committed_id = "committed", entity, eid
        db.add(ExtractionReview(data_point_id=p.id, user_id=user_id,
                                action="override" if reason else "confirm", override_reason=reason))
        committed.append({"point_id": p.id, "entity": entity, "id": eid, "notes": notes})
    for (cb_code, vdate), pts in projections_by_vintage.items():
        cb = da.cb_by_code(db, cb_code)
        if cb is None:
            raise ValueError(f"Unknown central bank {cb_code}")
        vd = date.fromisoformat(vdate) if vdate else date.today()
        vint = ProjectionVintage(central_bank_id=cb.id, vintage_date=vd,
                                 label=f"{cb.short_name} projections {vd.strftime('%B %Y')}",
                                 source_url=sub.url, input_method=sub.input_method,
                                 verification_status=(VerificationStatus.USER_CONFIRMED.value if confirm
                                                      else VerificationStatus.UNVERIFIED.value))
        db.add(vint)
        db.flush()
        for p in pts:
            f = p.fields
            db.add(CentralBankProjection(vintage_id=vint.id, central_bank_id=cb.id, variable=f["variable"],
                                         target_period=str(f["target_period"]), value=float(f["value"]),
                                         range_low=_num(f.get("range_low")), range_high=_num(f.get("range_high"))))
            p.status, p.committed_entity, p.committed_id = "committed", "projection_vintage", vint.id
            db.add(ExtractionReview(data_point_id=p.id, user_id=user_id, action="confirm"))
        committed.append({"entity": "projection_vintage", "id": vint.id,
                          "notes": [f"New vintage stored ({len(pts)} values); older vintages kept"]})
        t = triggers["projection_vintage"]
        t["central_banks"].add(cb.code)
        t["currencies"].add(cb.currency)
        t["vintage_ids"].add(vint.id)
    sub.status = "committed"
    audit(db, "manual_submission", sub.id, "committed", user_id, rows=len(committed),
          confirm=confirm.get("basis") if confirm else None)
    db.commit()
    jobs = []
    if run_recompute:
        for entity, ctx in triggers.items():
            first_id = next(iter(ctx.get("release_ids") or ctx.get("statement_ids") or ctx.get("vintage_ids")
                                 or [None]))
            job = recompute.trigger(db, entity, first_id, **ctx)
            jobs.append({"id": job.id, "status": job.status, "summary": job.summary})
    return {"submission_id": sub.id, "committed": committed, "recompute_jobs": jobs, "skipped": problems}


def delete_upload(db: Session, sub_id: int, user_id: int | None = None) -> dict:
    """User deletes their upload: the original file record is removed from use, derived
    records are marked source-removed (superseded) and analysis is re-run (66.16)."""
    from app.services import recompute

    sub = db.get(ManualSubmission, sub_id)
    if sub is None:
        raise LookupError("Submission not found")
    sub.source_removed = True
    affected = list(db.scalars(select(EconomicRelease).where(EconomicRelease.submission_id == sub_id)))
    ctx = defaultdict(set)
    for r in affected:
        r.is_current = False
        r.verification_status = VerificationStatus.SUPERSEDED.value
        ctx["release_ids"].add(r.id)
        ind = db.get(Indicator, r.indicator_id)
        ctx["indicator_ids"].add(ind.id)
        ctx["currencies"].add(ind.currency)
        if ind.central_bank_code:
            ctx["central_banks"].add(ind.central_bank_code)
        # restore the previous value it replaced, if any
        prev = db.scalar(select(EconomicRelease).where(EconomicRelease.superseded_by_id == r.id))
        if prev is not None:
            prev.is_current = True
            prev.verification_status = (VerificationStatus.VERIFIED.value if prev.input_method == "automated"
                                        else VerificationStatus.UNVERIFIED.value)
    audit(db, "manual_submission", sub_id, "source_removed", user_id, releases=len(affected))
    db.commit()
    job = recompute.trigger(db, "release", None, **ctx) if affected else None
    return {"submission_id": sub_id, "releases_removed": len(affected),
            "recompute": job.summary if job else None}


# ---------------------------------------------------------------------------
# Quick edits from the economic calendar (click a number, type, Enter)

QUICK_FIELDS = ("actual", "consensus", "previous")


def quick_edit_event(db: Session, event_id: int, field: str, value: float | None, user_id: int | None = None,
                     reason: str | None = None) -> dict:
    """Edit one number on a calendar row.

    Forecast (consensus) and previous are stored on the event directly. An actual goes through the
    normal manual-data path (validation, revisions, verification, audit, re-analysis), exactly as if
    it had been typed into Data input, so a quick edit is never a shortcut around the checks."""
    from app.services import recompute

    if field not in QUICK_FIELDS:
        raise ValueError(f"Field must be one of {', '.join(QUICK_FIELDS)}")
    ev = db.get(EconomicEvent, event_id)
    if ev is None:
        raise LookupError("Event not found")
    ind = db.get(Indicator, ev.indicator_id)

    if field in ("consensus", "previous"):
        before = getattr(ev, field)
        setattr(ev, field, value)
        if field == "consensus":
            ev.consensus_source = "manual" if value is not None else None
        audit(db, "economic_event", ev.id, f"edited {field}", user_id, before=before, after=value)
        db.commit()
        rel = da.current_release(db, ind.id, ev.reference_period)
        jobs = []
        if rel is not None:  # the surprise depends on the forecast, so re-analyse
            job = recompute.trigger(db, "release", rel.id, release_ids={rel.id}, indicator_ids={ind.id},
                                    currencies={ind.currency},
                                    central_banks={ind.central_bank_code} if ind.central_bank_code else set())
            jobs.append({"id": job.id, "status": job.status, "summary": job.summary})
        return {"event_id": ev.id, "field": field, "value": value, "recompute_jobs": jobs}

    if value is None:
        raise ValueError("To remove an actual, delete the upload it came from on Data health")
    res = quick_release(db, ind, ev.reference_period, value, user_id, reason, "Calendar edit", "calendar_edit",
                        consensus=ev.consensus, previous=ev.previous,
                        release_date=ev.scheduled_at.date().isoformat() if ev.scheduled_at else None)
    return {"event_id": ev.id, "field": field, "value": value, **res}


def quick_release(db: Session, ind: Indicator, period: str, value: float, user_id: int | None, reason: str | None,
                  source_name: str, method: str, consensus: float | None = None, previous: float | None = None,
                  release_date: str | None = None) -> dict:
    """Save one typed number as a release through the normal manual-data path (validation, revisions,
    verification, audit, re-analysis). Raises CommitBlocked when the value needs a fix or a reason."""
    sub = _new_submission(db, InputMethod.TYPED.value, user_id,
                          {"indicator_code": ind.code, "reference_period": period})
    sub.content_type, sub.content_type_confidence = "economic_release", 100.0
    sub.raw_text = f"{ind.name} {period}: {value} ({source_name.lower()})"
    fields = {"indicator_code": ind.code, "indicator_text": ind.name, "reference_period": period,
              "actual": value, "consensus": consensus, "previous": previous, "unit": ind.unit,
              "country": ind.country, "currency": ind.currency, "source_name": source_name}
    if release_date:
        fields["release_date"] = release_date
    p = ExtractedDataPoint(submission_id=sub.id, row_index=0, kind="economic_release", fields=fields,
                           field_confidence={k: 100.0 for k in fields})
    _validate_point(db, p)
    db.add(p)
    audit(db, "manual_submission", sub.id, "submitted", user_id, method=method)
    db.commit()
    res = commit(db, sub.id, user_id, rows=[{"id": p.id, "include": True, "override_reason": reason}])
    if res.get("skipped"):
        raise CommitBlocked(res["skipped"])
    return res
