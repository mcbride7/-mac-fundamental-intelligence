"""Verification rules (Section 66.10): how a data point's status and confirmation
basis translate into evidence quality, trade-grade caps and UI badges.

Pure functions — no database access — so they are easy to test and reuse."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.core.enums import GRADE_ORDER, ConfirmationBasis, Grade, VerificationStatus

# Weight (0..1) that a data point contributes to Evidence Quality.
_WEIGHTS = {
    (VerificationStatus.VERIFIED, None): 1.00,
    (VerificationStatus.USER_CONFIRMED, ConfirmationBasis.OFFICIAL_SOURCE): 0.95,
    (VerificationStatus.USER_CONFIRMED, ConfirmationBasis.SECONDARY_SOURCE): 0.85,
    (VerificationStatus.USER_CONFIRMED, ConfirmationBasis.NO_SOURCE): 0.70,
    (VerificationStatus.UNVERIFIED, None): 0.50,
    (VerificationStatus.CONFLICT, None): 0.0,
    (VerificationStatus.SUPERSEDED, None): 0.0,
}


@dataclass(frozen=True)
class DataPointStatus:
    status: str
    basis: str | None = None
    extraction_confidence: float | None = None  # 0..100, manual uploads only
    critical: bool = True  # does the analysis depend critically on this point?
    label: str = ""


def evidence_weight(status: str, basis: str | None = None, extraction_confidence: float | None = None) -> float:
    st = VerificationStatus(status)
    key_basis = ConfirmationBasis(basis) if (st == VerificationStatus.USER_CONFIRMED and basis) else None
    if st == VerificationStatus.USER_CONFIRMED and key_basis is None:
        key_basis = ConfirmationBasis.NO_SOURCE
    w = _WEIGHTS[(st, key_basis)]
    # Low extraction confidence reduces quality further, only while unverified by the system.
    if extraction_confidence is not None and st in (
        VerificationStatus.UNVERIFIED,
        VerificationStatus.USER_CONFIRMED,
    ):
        factor = max(0.5, min(1.0, extraction_confidence / 100.0))
        if st == VerificationStatus.USER_CONFIRMED:
            # A human confirmed the value, so OCR confidence matters much less.
            factor = 0.9 + 0.1 * factor
        w *= factor
    return round(w, 4)


def evidence_quality(points: Iterable[DataPointStatus], base: float = 100.0) -> float:
    """Average weight of the inputs, scaled to 0..100. Critical inputs count double."""
    pts = list(points)
    if not pts:
        return 0.0
    num = den = 0.0
    for p in pts:
        k = 2.0 if p.critical else 1.0
        num += k * evidence_weight(p.status, p.basis, p.extraction_confidence)
        den += k
    return round(base * num / den, 1)


def grade_cap(points: Iterable[DataPointStatus]) -> tuple[Grade | None, str | None, str]:
    """Return (max allowed grade or None, reason, data_status label) for a trade setup."""
    pts = list(points)
    critical = [p for p in pts if p.critical]
    statuses = {VerificationStatus(p.status) for p in critical}

    if VerificationStatus.CONFLICT in statuses:
        return Grade.NO_TRADE, "Critical data is in CONFLICT with the official source", "Data conflict"
    if VerificationStatus.UNVERIFIED in statuses:
        return Grade.A, "Relies on unverified data", "PENDING VERIFICATION"
    no_source = any(
        VerificationStatus(p.status) == VerificationStatus.USER_CONFIRMED
        and (p.basis in (None, ConfirmationBasis.NO_SOURCE.value))
        for p in critical
    )
    if no_source:
        return Grade.A, "Relies on user-confirmed data without a source", "Relies on user-confirmed data"
    if VerificationStatus.USER_CONFIRMED in statuses:
        return None, None, "Relies on user-confirmed data"
    return None, None, "All verified"


def apply_cap(grade: Grade, cap: Grade | None) -> Grade:
    if cap is None:
        return grade
    return cap if GRADE_ORDER.index(grade) > GRADE_ORDER.index(cap) else grade


def badge(status: str, basis: str | None = None, source_name: str | None = None) -> str:
    st = VerificationStatus(status)
    if st == VerificationStatus.VERIFIED:
        return "Verified"
    if st == VerificationStatus.USER_CONFIRMED:
        b = {
            ConfirmationBasis.OFFICIAL_SOURCE.value: "official source",
            ConfirmationBasis.SECONDARY_SOURCE.value: "secondary source",
            ConfirmationBasis.NO_SOURCE.value: "no source",
            None: "no source",
        }.get(basis, "no source")
        return f"User-confirmed ({b}{': ' + source_name if source_name else ''})"
    if st == VerificationStatus.UNVERIFIED:
        return "Unverified user-supplied data"
    if st == VerificationStatus.CONFLICT:
        return "Conflict with official source"
    return "Superseded"
