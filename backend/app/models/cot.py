"""CFTC Commitments of Traders (Legacy, futures only): one row per market per weekly report."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class CotWeek(Base):
    __tablename__ = "cot_weeks"
    __table_args__ = (UniqueConstraint("code", "report_date", name="uq_cot_week"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), index=True)          # CFTC contract market code
    report_date: Mapped[date] = mapped_column(Date, index=True)       # Tuesday the positions are as of
    oi: Mapped[int] = mapped_column(Integer)                          # open interest
    ncl: Mapped[int] = mapped_column(Integer)                         # non-commercial (speculator) long
    ncs: Mapped[int] = mapped_column(Integer)                         # non-commercial short
    cl: Mapped[int] = mapped_column(Integer)                          # commercial (hedger) long
    cs: Mapped[int] = mapped_column(Integer)                          # commercial short
    nrl: Mapped[int | None] = mapped_column(Integer)                  # non-reportable (small trader) long
    nrs: Mapped[int | None] = mapped_column(Integer)                  # non-reportable short
    price: Mapped[float | None] = mapped_column(Float)
    price_source: Mapped[str | None] = mapped_column(String(32))      # FRED | Twelve Data | manual
    input_method: Mapped[str] = mapped_column(String(16), default="automated")  # automated | file | manual | bundled
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
