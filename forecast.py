"""Forecast errors, accuracy, bias and revisions (Phase 3)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class ForecastError(Base):
    """Three-way comparison for one release: central bank vs market vs actual."""

    __tablename__ = "forecast_errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("economic_releases.id"), index=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey("economic_indicators.id"), index=True)
    central_bank_id: Mapped[int | None] = mapped_column(ForeignKey("central_banks.id"), index=True)
    projection_id: Mapped[int | None] = mapped_column(ForeignKey("central_bank_projections.id"))
    variable: Mapped[str | None] = mapped_column(String(32))
    actual: Mapped[float] = mapped_column(Float)
    cb_projection: Mapped[float | None] = mapped_column(Float)
    market_forecast: Mapped[float | None] = mapped_column(Float)
    economist_forecast: Mapped[float | None] = mapped_column(Float)
    cb_error: Mapped[float | None] = mapped_column(Float)
    market_error: Mapped[float | None] = mapped_column(Float)
    economist_error: Mapped[float | None] = mapped_column(Float)
    cb_classification: Mapped[str | None] = mapped_column(String(40))
    more_accurate: Mapped[str | None] = mapped_column(String(24))
    basis: Mapped[str] = mapped_column(String(12), default="real_time")  # real_time | final
    miss_explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastAccuracy(Base):
    __tablename__ = "forecast_accuracy"
    id: Mapped[int] = mapped_column(primary_key=True)
    forecaster: Mapped[str] = mapped_column(String(32), index=True)  # FED | ECB | market | economist
    variable: Mapped[str] = mapped_column(String(32), index=True)
    window: Mapped[str] = mapped_column(String(16))  # last4 | last8 | last12 | 2y | 5y
    basis: Mapped[str] = mapped_column(String(12), default="real_time")
    n: Mapped[int] = mapped_column(Integer)
    mae: Mapped[float] = mapped_column(Float)
    rmse: Mapped[float] = mapped_column(Float)
    mean_error: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)  # 0..100
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastBias(Base):
    __tablename__ = "forecast_bias"
    id: Mapped[int] = mapped_column(primary_key=True)
    forecaster: Mapped[str] = mapped_column(String(32), index=True)
    variable: Mapped[str] = mapped_column(String(32))
    classification: Mapped[str] = mapped_column(String(48))
    mean_error: Mapped[float] = mapped_column(Float)
    hit_rate_same_sign: Mapped[float] = mapped_column(Float)
    n: Mapped[int] = mapped_column(Integer)
    t_stat: Mapped[float | None] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text, default="")
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForecastRevision(Base):
    __tablename__ = "forecast_revisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    central_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"), index=True)
    variable: Mapped[str] = mapped_column(String(32))
    target_period: Mapped[str] = mapped_column(String(16))
    path: Mapped[list] = mapped_column(JSON, default=list)  # [{"vintage": "2026-03", "value": 1.8}, ...]
    momentum: Mapped[str] = mapped_column(String(16))  # POSITIVE | NEGATIVE | FLAT | MIXED
    total_change: Mapped[float] = mapped_column(Float)
    interpretation: Mapped[str] = mapped_column(Text, default="")
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
