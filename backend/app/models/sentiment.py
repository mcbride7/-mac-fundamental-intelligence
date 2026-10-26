"""Retail trader sentiment: share of retail positions that are long, per symbol."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class RetailSentiment(Base):
    __tablename__ = "retail_sentiment"
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)   # EURUSD, XAUUSD ...
    long_pct: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32))               # Myfxbook | manual
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
