"""Sources, central banks, indicators, events and releases (Phase 1)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import InputMethod, SourceStatus, VerificationStatus
from app.db import Base, utcnow


class Source(Base):
    """Source registry. Tier 1 = official, 2 = institutions/data providers, 3 = news,
    4 = other, M = user-supplied manual data."""

    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    tier: Mapped[str] = mapped_column(String(2), default="1")
    kind: Mapped[str] = mapped_column(String(40), default="api")  # api | rss | scraper | manual | csv
    url: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(8))
    central_bank_code: Mapped[str | None] = mapped_column(String(16))
    freshness_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceHealth(Base):
    __tablename__ = "source_health"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), unique=True)
    status: Mapped[str] = mapped_column(String(16), default=SourceStatus.UNKNOWN.value)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_next_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retries: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    records_last_run: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[Source] = relationship()


class SourceDocument(Base):
    """Every retrieved or uploaded document (statements, PDFs, pages)."""

    __tablename__ = "source_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    url: Mapped[str | None] = mapped_column(String(1000))
    title: Mapped[str | None] = mapped_column(String(500))
    doc_type: Mapped[str | None] = mapped_column(String(40))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    content_text: Mapped[str | None] = mapped_column(Text)
    input_method: Mapped[str] = mapped_column(String(16), default=InputMethod.AUTOMATED.value)


class CentralBank(Base):
    __tablename__ = "central_banks"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # FED, ECB, ...
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str] = mapped_column(String(32))
    country: Mapped[str] = mapped_column(String(8))
    currency: Mapped[str] = mapped_column(String(8))
    website: Mapped[str | None] = mapped_column(String(300))
    current_rate: Mapped[float | None] = mapped_column(Float)
    previous_rate: Mapped[float | None] = mapped_column(Float)
    last_decision: Mapped[str | None] = mapped_column(String(16))  # HIKE | CUT | HOLD
    last_decision_date: Mapped[date | None] = mapped_column(Date)
    inflation_target: Mapped[float | None] = mapped_column(Float)
    publishes: Mapped[list] = mapped_column(JSON, default=list)  # projection variables published


class Indicator(Base):
    __tablename__ = "economic_indicators"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # US_CPI_YOY
    name: Mapped[str] = mapped_column(String(200))
    country: Mapped[str] = mapped_column(String(8), index=True)
    currency: Mapped[str] = mapped_column(String(8), index=True)
    category: Mapped[str] = mapped_column(String(32))  # inflation | employment | growth | ...
    unit: Mapped[str] = mapped_column(String(16), default="%")  # % | index | k | m | bn | bps | level
    frequency: Mapped[str] = mapped_column(String(16), default="monthly")
    importance: Mapped[str] = mapped_column(String(8), default="medium")  # high | medium | low
    transform: Mapped[str | None] = mapped_column(String(16))  # yoy | mom | level | qoq_saar
    higher_is: Mapped[str] = mapped_column(String(16), default="hawkish")  # hawkish | dovish | neutral
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    fred_series: Mapped[str | None] = mapped_column(String(64))
    official_source_key: Mapped[str | None] = mapped_column(String(64))
    central_bank_code: Mapped[str | None] = mapped_column(String(16))
    projection_variable: Mapped[str | None] = mapped_column(String(32))  # maps to CB projection var


class EconomicEvent(Base):
    """A scheduled calendar event (a release slot)."""

    __tablename__ = "economic_events"
    __table_args__ = (UniqueConstraint("indicator_id", "reference_period", name="uq_event_period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey("economic_indicators.id"), index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reference_period: Mapped[str] = mapped_column(String(16))  # 2026-09, 2026Q3
    importance: Mapped[str | None] = mapped_column(String(8))
    event_type: Mapped[str] = mapped_column(String(32), default="release")  # release | cb_decision | speech
    previous: Mapped[float | None] = mapped_column(Float)
    consensus: Mapped[float | None] = mapped_column(Float)
    consensus_source: Mapped[str | None] = mapped_column(String(100))
    indicator: Mapped[Indicator] = relationship()


class EconomicRelease(Base):
    """An actual value for an event. Revisions are new rows (revision_number > 0);
    nothing is ever overwritten."""

    __tablename__ = "economic_releases"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("economic_events.id"), index=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey("economic_indicators.id"), index=True)
    reference_period: Mapped[str] = mapped_column(String(16), index=True)
    actual: Mapped[float] = mapped_column(Float)
    previous: Mapped[float | None] = mapped_column(Float)
    consensus: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16), default="%")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_number: Mapped[int] = mapped_column(Integer, default=0)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    source_name: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    input_method: Mapped[str] = mapped_column(String(16), default=InputMethod.AUTOMATED.value)
    verification_status: Mapped[str] = mapped_column(
        String(20), default=VerificationStatus.VERIFIED.value, index=True
    )
    confirmation_basis: Mapped[str | None] = mapped_column(String(24))
    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("manual_submissions.id"))
    superseded_by_id: Mapped[int | None] = mapped_column(ForeignKey("economic_releases.id"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    indicator: Mapped[Indicator] = relationship(foreign_keys=[indicator_id])


class EconomicForecast(Base):
    """Market / economist consensus snapshots for an event (kept as history)."""

    __tablename__ = "economic_forecasts"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("economic_events.id"), index=True)
    forecaster: Mapped[str] = mapped_column(String(32), default="market")  # market | economist
    value: Mapped[float] = mapped_column(Float)
    source_name: Mapped[str | None] = mapped_column(String(200))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    input_method: Mapped[str] = mapped_column(String(16), default=InputMethod.AUTOMATED.value)


class IndicatorObservation(Base):
    """Raw series observations from providers such as FRED (levels, before transforms)."""

    __tablename__ = "indicator_observations"
    __table_args__ = (UniqueConstraint("series", "obs_date", "vintage", name="uq_obs"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    series: Mapped[str] = mapped_column(String(64), index=True)
    obs_date: Mapped[date] = mapped_column(Date)
    value: Mapped[float] = mapped_column(Float)
    vintage: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
