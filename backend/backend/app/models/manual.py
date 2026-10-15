"""Manual ingestion, user confirmation, verification and reconciliation (Section 66)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class ManualSubmission(Base):
    __tablename__ = "manual_submissions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    input_method: Mapped[str] = mapped_column(String(16))
    content_type: Mapped[str] = mapped_column(String(32), default="unknown")
    content_type_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    raw_text: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    hint: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. {"indicator": "US_CPI_YOY"}
    status: Mapped[str] = mapped_column(String(16), default="extracted")  # extracted|committed|discarded|failed
    error: Mapped[str | None] = mapped_column(Text)
    source_removed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ManualSubmissionFile(Base):
    __tablename__ = "manual_submission_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("manual_submissions.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractedDataPoint(Base):
    """One extracted row awaiting review. `fields` holds the editable values,
    `field_confidence` the per-field extraction confidence (0-100)."""

    __tablename__ = "extracted_data_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("manual_submissions.id"), index=True)
    row_index: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(32), default="economic_release")
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    field_confidence: Mapped[dict] = mapped_column(JSON, default=dict)
    indicator_code: Mapped[str | None] = mapped_column(String(64))
    mapping_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|committed|discarded
    committed_entity: Mapped[str | None] = mapped_column(String(48))
    committed_id: Mapped[int | None] = mapped_column(Integer)


class ExtractionReview(Base):
    __tablename__ = "extraction_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    data_point_id: Mapped[int] = mapped_column(ForeignKey("extracted_data_points.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(16))  # confirm | edit | discard | override
    changes: Mapped[dict] = mapped_column(JSON, default=dict)
    override_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DataConfirmation(Base):
    """A user's confirmation that a value is correct when the system cannot verify it."""

    __tablename__ = "data_confirmations"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("economic_releases.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    basis: Mapped[str] = mapped_column(String(24))
    source_name: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    evidence_file_id: Mapped[int | None] = mapped_column(ForeignKey("manual_submission_files.id"))
    note: Mapped[str | None] = mapped_column(Text)
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("economic_releases.id"), index=True)
    source_key: Mapped[str | None] = mapped_column(String(64))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    outcome: Mapped[str] = mapped_column(String(16))  # match | mismatch | revision | unreachable | no_data
    official_value: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)


class DataReconciliation(Base):
    __tablename__ = "data_reconciliation"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("economic_releases.id"), index=True)
    official_release_id: Mapped[int | None] = mapped_column(ForeignKey("economic_releases.id"))
    manual_value: Mapped[float] = mapped_column(Float)
    official_value: Mapped[float] = mapped_column(Float)
    official_source: Mapped[str | None] = mapped_column(String(200))
    prior_status: Mapped[str] = mapped_column(String(20))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution: Mapped[str | None] = mapped_column(String(24))  # use_official | keep_manual
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
