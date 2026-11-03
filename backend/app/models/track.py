"""Track record: every trade grade the app gives, and what the market did next."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class SignalRecord(Base):
    """One graded setup (A+, A, B or C with a direction), frozen when it was given.
    Returns are measured in the signal's direction: +0.8 means the call made 0.8%."""

    __tablename__ = "signal_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # LONG | SHORT
    grade: Mapped[str] = mapped_column(String(12), index=True)
    confluence: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    entry_price: Mapped[float | None] = mapped_column(Float)
    entry_price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ret_1d: Mapped[float | None] = mapped_column(Float)
    ret_5d: Mapped[float | None] = mapped_column(Float)
    ret_20d: Mapped[float | None] = mapped_column(Float)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(200))


class SignalPlan(Base):
    """Stop loss, take profit and trade type for one call (own table so existing databases pick it up).
    Levels are set automatically from recent volatility and can be overwritten by hand."""

    __tablename__ = "signal_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    trade_type: Mapped[str] = mapped_column(String(8), default="swing")  # swing | day
    type_reason: Mapped[str | None] = mapped_column(String(200))
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    atr_pct: Mapped[float | None] = mapped_column(Float)  # typical daily move used to size the levels, in %
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    outcome: Mapped[str | None] = mapped_column(String(16))  # target | stop | expired
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_r: Mapped[float | None] = mapped_column(Float)  # +2 = made twice the risk, -1 = lost the risk
