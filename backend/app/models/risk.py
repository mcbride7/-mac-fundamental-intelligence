"""Risk-on / risk-off sentiment readings (see analytics/risk.py)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class RiskSentiment(Base):
    __tablename__ = "risk_sentiment"
    id: Mapped[int] = mapped_column(primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    data_date: Mapped[str | None] = mapped_column(String(10))  # latest market day used
    score: Mapped[float | None] = mapped_column(Float)          # 0..100
    label: Mapped[str] = mapped_column(String(16))              # Risk-On | Risk-Off | Neutral | No data
    components: Mapped[list] = mapped_column(JSON, default=list)
    missing: Mapped[list] = mapped_column(JSON, default=list)
    coverage: Mapped[float] = mapped_column(Float, default=0.0)
    divergence: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[list] = mapped_column(JSON, default=list)
