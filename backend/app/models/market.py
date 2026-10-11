"""Market prices, yields, rate expectations, reactions and surprises (Phase 4).
market_prices, bond_yields and rate_expectations become TimescaleDB hypertables."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import InputMethod, VerificationStatus
from app.db import Base, utcnow


class MarketPrice(Base):
    __tablename__ = "market_prices"
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)  # EURUSD, XAUUSD, SPX, BTCUSD, DXY
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    price: Mapped[float] = mapped_column(Float)
    asset_class: Mapped[str] = mapped_column(String(16), default="fx")
    source: Mapped[str | None] = mapped_column(String(64))
    input_method: Mapped[str] = mapped_column(String(16), default=InputMethod.AUTOMATED.value)
    verification_status: Mapped[str] = mapped_column(String(20), default=VerificationStatus.VERIFIED.value)


class BondYield(Base):
    __tablename__ = "bond_yields"
    country: Mapped[str] = mapped_column(String(8), primary_key=True)
    tenor: Mapped[str] = mapped_column(String(8), primary_key=True)  # 2Y 5Y 10Y 30Y
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    yield_pct: Mapped[float] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(64))
    input_method: Mapped[str] = mapped_column(String(16), default=InputMethod.AUTOMATED.value)


class YieldCurve(Base):
    """Derived curve snapshot (2s10s etc.)."""

    __tablename__ = "yield_curves"
    id: Mapped[int] = mapped_column(primary_key=True)
    country: Mapped[str] = mapped_column(String(8), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    points: Mapped[dict] = mapped_column(JSON, default=dict)  # {"2Y": 4.1, "10Y": 4.3}
    slope_2s10s_bps: Mapped[float | None] = mapped_column(Float)
    shape: Mapped[str | None] = mapped_column(String(16))  # NORMAL | FLAT | INVERTED


class RateExpectation(Base):
    """Market-implied probabilities for the next meeting (cut/hold/hike) and implied path."""

    __tablename__ = "rate_expectations"
    central_bank_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    meeting_date: Mapped[str | None] = mapped_column(String(16))
    prob_cut: Mapped[float] = mapped_column(Float, default=0.0)
    prob_hold: Mapped[float] = mapped_column(Float, default=0.0)
    prob_hike: Mapped[float] = mapped_column(Float, default=0.0)
    implied_change_bps: Mapped[float | None] = mapped_column(Float)
    implied_12m_change_bps: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(64))
    input_method: Mapped[str] = mapped_column(String(16), default=InputMethod.AUTOMATED.value)


class EconomicSurprise(Base):
    __tablename__ = "economic_surprises"
    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("economic_releases.id"), index=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey("economic_indicators.id"), index=True)
    market_surprise: Mapped[float | None] = mapped_column(Float)
    cb_surprise: Mapped[float | None] = mapped_column(Float)
    historical_z: Mapped[float | None] = mapped_column(Float)
    classification: Mapped[str] = mapped_column(String(40))
    policy_direction: Mapped[str] = mapped_column(String(16))  # Hawkish | Dovish | Neutral
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketReaction(Base):
    __tablename__ = "market_reactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_entity: Mapped[str] = mapped_column(String(32))  # release | meeting | statement
    event_id: Mapped[int] = mapped_column(Integer, index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    windows: Mapped[dict] = mapped_column(JSON, default=dict)  # {"5m": {"EURUSD": -0.12, "US2Y": 3.0}}
    expected: Mapped[dict] = mapped_column(JSON, default=dict)  # expected sign per asset
    divergences: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
