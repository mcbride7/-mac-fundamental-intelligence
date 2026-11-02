"""Central bank press conferences: the transcript and its analysis."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class PressConference(Base):
    __tablename__ = "press_conferences"
    id: Mapped[int] = mapped_column(primary_key=True)
    central_bank_id: Mapped[int] = mapped_column(ForeignKey("central_banks.id"), index=True)
    held_on: Mapped[date] = mapped_column(Date, index=True)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(1000))
    text: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    input_method: Mapped[str] = mapped_column(String(16), default="automated")  # automated | pasted | url
    tone: Mapped[float | None] = mapped_column(Float)                 # -100 dovish .. +100 hawkish
    vs_statement: Mapped[float | None] = mapped_column(Float)         # tone minus the decision statement's tone
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    questions: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
