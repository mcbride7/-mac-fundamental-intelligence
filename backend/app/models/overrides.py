"""Numbers typed over a calculated value (e.g. a surprise you set yourself on the calendar).
Kept in their own table so the calculated value is never lost and the override can be cleared."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class EventOverride(Base):
    __tablename__ = "event_overrides"
    __table_args__ = (UniqueConstraint("event_id", "field", name="uq_event_override"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, index=True)
    field: Mapped[str] = mapped_column(String(32))  # surprise
    value: Mapped[float] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(300))
    user_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
