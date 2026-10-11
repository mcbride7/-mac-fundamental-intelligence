"""Central-bank meetings, statements, speeches, projections and policy scores (Phases 2-3)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import InputMethod, VerificationStatus
from app.db import Base, utcnow


class CentralBankMeeting(Base):
    __tablename__ = "central_bank_meetings"
    id: Mapped[int] = mapped_column(primary_key=True)
    central_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"), index=True)
    meeting_date: Mapped[date] = mapped_column(Date, index=True)
    decision: Mapped[str | None] = mapped_column(String(16))  # HIKE | CUT | HOLD
    rate_before: Mapped[float | None] = mapped_column(Float)
    rate_after: Mapped[float | None] = mapped_column(Float)
    change_bps: Mapped[float | None] = mapped_column(Float)
    votes: Mapped[dict] = mapped_column(JSON, default=dict)  # {"for": 9, "against": 2, "dissent": [...]}
    # Pre-meeting expectations (Section 11)
    expected_decision: Mapped[str | None] = mapped_column(String(16))
    expected_change_bps: Mapped[float | None] = mapped_column(Float)
    expected_tone: Mapped[float | None] = mapped_column(Float)  # -100..+100 market-expected tone
    expected_wording: Mapped[str | None] = mapped_column(Text)
    economist_consensus: Mapped[str | None] = mapped_column(String(64))
    surprise_score: Mapped[float | None] = mapped_column(Float)  # -100 dovish .. +100 hawkish
    is_scheduled: Mapped[bool] = mapped_column(Boolean, default=True)


class CentralBankStatement(Base):
    __tablename__ = "central_bank_statements"
    id: Mapped[int] = mapped_column(primary_key=True)
    central_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"), index=True)
    meeting_id: Mapped[int | None] = mapped_column(ForeignKey("central_bank_meetings.id"))
    doc_type: Mapped[str] = mapped_column(String(32), default="statement")  # statement|minutes|press_conference
    title: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    meeting_date: Mapped[date | None] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    input_method: Mapped[str] = mapped_column(String(16), default=InputMethod.AUTOMATED.value)
    verification_status: Mapped[str] = mapped_column(String(20), default=VerificationStatus.VERIFIED.value)
    tone_score: Mapped[float | None] = mapped_column(Float)  # -100..+100 language tone
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CentralBankStatementVersion(Base):
    """Stored comparison between two consecutive statements (Sections 7-9)."""

    __tablename__ = "central_bank_statement_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    central_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"), index=True)
    previous_statement_id: Mapped[int] = mapped_column(ForeignKey("central_bank_statements.id"))
    latest_statement_id: Mapped[int] = mapped_column(ForeignKey("central_bank_statements.id"), index=True)
    changes: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CentralBankSpeech(Base):
    __tablename__ = "central_bank_speeches"
    id: Mapped[int] = mapped_column(primary_key=True)
    central_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"), index=True)
    speaker: Mapped[str] = mapped_column(String(200))
    role: Mapped[str | None] = mapped_column(String(100))  # governor | deputy | board member
    title: Mapped[str | None] = mapped_column(String(500))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    text: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    tone_score: Mapped[float | None] = mapped_column(Float)
    input_method: Mapped[str] = mapped_column(String(16), default=InputMethod.AUTOMATED.value)


class ProjectionVintage(Base):
    """One projection round (e.g. Fed SEP September 2026). Never overwritten."""

    __tablename__ = "central_bank_projection_vintages"
    id: Mapped[int] = mapped_column(primary_key=True)
    central_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"), index=True)
    vintage_date: Mapped[date] = mapped_column(Date, index=True)
    label: Mapped[str] = mapped_column(String(100))  # "September 2026 SEP"
    source_url: Mapped[str | None] = mapped_column(String(1000))
    input_method: Mapped[str] = mapped_column(String(16), default=InputMethod.AUTOMATED.value)
    verification_status: Mapped[str] = mapped_column(String(20), default=VerificationStatus.VERIFIED.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CentralBankProjection(Base):
    """A single projected value within a vintage, e.g. Core PCE for 2026 = 3.0%."""

    __tablename__ = "central_bank_projections"
    id: Mapped[int] = mapped_column(primary_key=True)
    vintage_id: Mapped[int] = mapped_column(ForeignKey("central_bank_projection_vintages.id"), index=True)
    central_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"), index=True)
    variable: Mapped[str] = mapped_column(String(32), index=True)  # gdp | inflation | core_inflation | unemployment | policy_rate
    target_period: Mapped[str] = mapped_column(String(16))  # 2026 | 2026Q4
    value: Mapped[float] = mapped_column(Float)
    range_low: Mapped[float | None] = mapped_column(Float)
    range_high: Mapped[float | None] = mapped_column(Float)


class PolicyScore(Base):
    __tablename__ = "policy_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    central_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    score: Mapped[float] = mapped_column(Float)  # 0..100 (100 = extremely hawkish)
    classification: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(24))  # RESTRICTIVE | NEUTRAL | ACCOMMODATIVE
    confidence: Mapped[float] = mapped_column(Float)
    components: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_quality: Mapped[float] = mapped_column(Float, default=100.0)
    previous_score: Mapped[float | None] = mapped_column(Float)
    shift: Mapped[float | None] = mapped_column(Float)
    shift_classification: Mapped[str | None] = mapped_column(String(40))
    explanation: Mapped[list] = mapped_column(JSON, default=list)


class PolicyDivergence(Base):
    __tablename__ = "policy_divergence"
    id: Mapped[int] = mapped_column(primary_key=True)
    base_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"))
    quote_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    score_divergence: Mapped[float] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    currency_implication: Mapped[str] = mapped_column(String(200))
