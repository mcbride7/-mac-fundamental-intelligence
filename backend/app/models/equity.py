"""Equity quotes from Finnhub (latest snapshot per symbol) and your own extra tickers."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class EquityQuote(Base):
    __tablename__ = "equity_quotes"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    price: Mapped[float | None] = mapped_column(Float)
    change: Mapped[float | None] = mapped_column(Float)
    change_pct: Mapped[float | None] = mapped_column(Float)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    prev_close: Mapped[float | None] = mapped_column(Float)
    quote_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EquityWatch(Base):
    """Tickers you added yourself (shown under 'My list')."""
    __tablename__ = "equity_watch"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(120))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
