"""News headlines from free feeds (central bank RSS, FX news RSS, Finnhub), tagged by currency and tone."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class NewsArticle(Base):
    __tablename__ = "news_articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(64), unique=True)          # hash of the link (or title)
    title: Mapped[str] = mapped_column(String(500))
    summary: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(1000))
    source_name: Mapped[str] = mapped_column(String(120))
    feed: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="news")      # central_bank | news
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    currencies: Mapped[list] = mapped_column(JSON, default=list)
    # the currencies the tone is about: named by country, bank or nickname, not just a pair code like GBP/USD
    # ("GBP/USD rallies on strong UK wages" is hawkish for GBP, not for USD)
    tone_currencies: Mapped[list | None] = mapped_column(JSON, default=None)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    tone: Mapped[str] = mapped_column(String(12), default="neutral")   # hawkish | dovish | neutral
    risk: Mapped[str | None] = mapped_column(String(12))               # risk_on | risk_off
    importance: Mapped[str] = mapped_column(String(8), default="normal")  # high | normal
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
