"""Macro regimes, currency scores, scenarios, trade analysis (Phases 4-7)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class MacroRegime(Base):
    __tablename__ = "macro_regimes"
    id: Mapped[int] = mapped_column(primary_key=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    primary: Mapped[str] = mapped_column(String(64))
    secondary: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation: Mapped[list] = mapped_column(JSON, default=list)


class CurrencyScore(Base):
    __tablename__ = "currency_scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(8), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    components: Mapped[dict] = mapped_column(JSON, default=dict)  # growth: +2, inflation: +3 ...
    total: Mapped[float] = mapped_column(Float)
    bias: Mapped[str] = mapped_column(String(16))
    evidence_quality: Mapped[float] = mapped_column(Float, default=100.0)
    previous_total: Mapped[float | None] = mapped_column(Float)
    data_status: Mapped[dict] = mapped_column(JSON, default=dict)


class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # base | bullish | bearish | risk
    title: Mapped[str] = mapped_column(String(300))
    narrative: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(8))  # up | down | flat
    probability: Mapped[float] = mapped_column(Float)
    drivers: Mapped[list] = mapped_column(JSON, default=list)
    activation: Mapped[list] = mapped_column(JSON, default=list)
    confirmation: Mapped[list] = mapped_column(JSON, default=list)
    invalidation: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)


class ScenarioProbability(Base):
    """History of scenario probabilities so changes can be alerted."""

    __tablename__ = "scenario_probabilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    probability: Mapped[float] = mapped_column(Float)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ScenarioTrigger(Base):
    __tablename__ = "scenario_triggers"
    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id"), index=True)
    trigger_type: Mapped[str] = mapped_column(String(16))  # activation | confirmation | invalidation
    description: Mapped[str] = mapped_column(Text)
    metric: Mapped[str | None] = mapped_column(String(64))  # e.g. US_CPI_YOY, US2Y, FED_POLICY_SCORE
    operator: Mapped[str | None] = mapped_column(String(4))  # > < >= <=
    threshold: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | met | not_met


class FundamentalAnalysis(Base):
    __tablename__ = "fundamental_analysis"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    bias: Mapped[str] = mapped_column(String(16))
    conviction: Mapped[float] = mapped_column(Float)
    evidence_quality: Mapped[float] = mapped_column(Float)
    forecast_confidence: Mapped[float] = mapped_column(Float)
    scenario_confidence: Mapped[float] = mapped_column(Float)
    time_horizon: Mapped[str] = mapped_column(String(32), default="1-4 weeks")
    differentials: Mapped[dict] = mapped_column(JSON, default=dict)
    report: Mapped[dict] = mapped_column(JSON, default=dict)  # professional response format (Section 59)


class TradeBias(Base):
    __tablename__ = "trade_biases"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    bias: Mapped[str] = mapped_column(String(16))
    previous_bias: Mapped[str | None] = mapped_column(String(16))


class TradeSetup(Base):
    __tablename__ = "trade_setups"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset: Mapped[str] = mapped_column(String(32), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    direction: Mapped[str] = mapped_column(String(8))  # LONG | SHORT | NONE
    grade: Mapped[str] = mapped_column(String(12))
    confluence_score: Mapped[float] = mapped_column(Float)
    factors: Mapped[dict] = mapped_column(JSON, default=dict)
    no_trade_reasons: Mapped[list] = mapped_column(JSON, default=list)
    data_status: Mapped[str] = mapped_column(String(48))
    grade_cap_reason: Mapped[str | None] = mapped_column(String(200))
    primary_driver: Mapped[str | None] = mapped_column(String(200))
    secondary_drivers: Mapped[list] = mapped_column(JSON, default=list)
    catalysts: Mapped[list] = mapped_column(JSON, default=list)
    confirmation: Mapped[list] = mapped_column(JSON, default=list)
    invalidation: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    alternative: Mapped[str | None] = mapped_column(Text)
    research_alerts: Mapped[list] = mapped_column(JSON, default=list)
