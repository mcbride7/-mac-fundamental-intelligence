"""Builds the per-currency fundamental snapshot that the policy, currency,
scenario and trading engines share. Every value carries the verification status
of the data behind it, so evidence quality and grade caps are always honest."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.verification import DataPointStatus, evidence_quality
from app.db import utcnow
from app.models import (
    BondYield,
    CentralBank,
    CentralBankStatement,
    EconomicRelease,
    EconomicSurprise,
    Indicator,
    MacroRegime,
    PolicyScore,
    RateExpectation,
)
from app.services import data_access as da

CURRENCIES = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "ZAR", "MXN", "CNY"]
COUNTRY = {"USD": "US", "EUR": "EA", "GBP": "GB", "JPY": "JP", "CHF": "CH", "CAD": "CA", "AUD": "AU",
           "NZD": "NZ", "ZAR": "ZA", "MXN": "MX", "CNY": "CN"}
YIELD_COUNTRY = {"USD": "US", "EUR": "DE", "GBP": "GB", "JPY": "JP", "CHF": "CH", "CAD": "CA", "AUD": "AU",
                 "NZD": "NZ", "ZAR": "ZA", "MXN": "MX", "CNY": "CN"}
HEADLINE_INFL = {"US": "US_CPI_YOY", "EA": "EA_HICP_YOY", "GB": "GB_CPI_YOY", "JP": "JP_CPI_YOY",
                 "CH": "CH_CPI_YOY", "CA": "CA_CPI_YOY", "AU": "AU_CPI_YOY", "NZ": "NZ_CPI_YOY",
                 "ZA": "ZA_CPI_YOY", "CN": "CN_CPI_YOY", "MX": "MX_CPI_YOY"}
UNEMP = {"US": "US_UNEMPLOYMENT", "EA": "EA_UNEMPLOYMENT", "GB": "GB_UNEMPLOYMENT", "CA": "CA_UNEMPLOYMENT",
         "AU": "AU_UNEMPLOYMENT"}
GDP = {"US": "US_GDP_QOQ", "EA": "EA_GDP_QOQ", "GB": "GB_GDP_QOQ", "ZA": "ZA_GDP_QOQ"}
PMI = {"US": "US_ISM_MANUF", "EA": "EA_PMI_COMPOSITE"}
POLICY_RATE = {"FED": "US_FED_RATE", "ECB": "EA_ECB_RATE", "BOE": "GB_BOE_RATE", "BOJ": "JP_BOJ_RATE",
               "SARB": "ZA_SARB_RATE"}
IMPORTANCE_W = {"high": 1.0, "medium": 0.6, "low": 0.3}


def _aware(ts):
    from datetime import timezone

    return ts if ts is None or ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@dataclass
class Snapshot:
    currency: str
    country: str
    cb: CentralBank | None
    policy_score: float | None = None
    policy_confidence: float | None = None
    policy_components: dict = field(default_factory=dict)
    policy_rate: float | None = None
    implied_change_bps: float | None = None
    implied_is_proxy: bool = False
    prob_cut: float | None = None
    prob_hike: float | None = None
    inflation: float | None = None
    inflation_target: float | None = None
    deviations: dict = field(default_factory=dict)  # variable -> actual - projection
    gdp_latest: float | None = None
    pmi: float | None = None
    unemployment_change_6m: float | None = None
    y2: float | None = None
    y10: float | None = None
    y2_change_1m_bps: float | None = None
    surprise_index: float | None = None
    statement_tone: float | None = None
    last_decision: str | None = None
    last_change_bps: float | None = None
    points: list = field(default_factory=list)  # DataPointStatus
    sources: list = field(default_factory=list)  # evidence for citations

    @property
    def evidence_quality(self) -> float:
        return evidence_quality(self.points) if self.points else 50.0


def _use(snap: Snapshot, rel: EconomicRelease | None, ind: Indicator | None, critical: bool, label: str):
    if rel is None:
        return None
    snap.points.append(DataPointStatus(rel.verification_status, rel.confirmation_basis,
                                       rel.extraction_confidence, critical, label))
    snap.sources.append({"type": "economic_release", "id": rel.id, "indicator": ind.code if ind else None,
                         "label": label, "period": rel.reference_period, "value": rel.actual,
                         "status": rel.verification_status, "basis": rel.confirmation_basis,
                         "source": rel.source_name, "input_method": rel.input_method})
    return rel.actual


def latest_yield(db: Session, country: str, tenor: str, before=None) -> BondYield | None:
    q = select(BondYield).where(BondYield.country == country, BondYield.tenor == tenor)
    if before is not None:
        q = q.where(BondYield.ts <= before)
    return db.scalar(q.order_by(BondYield.ts.desc()))


def latest_rate_expectation(db: Session, cb_code: str, before=None) -> RateExpectation | None:
    q = select(RateExpectation).where(RateExpectation.central_bank_code == cb_code)
    if before is not None:
        q = q.where(RateExpectation.ts < before)
    return db.scalar(q.order_by(RateExpectation.ts.desc()))


def latest_policy_score(db: Session, cb_id: int) -> PolicyScore | None:
    return db.scalar(select(PolicyScore).where(PolicyScore.central_bank_id == cb_id)
                     .order_by(PolicyScore.as_of.desc(), PolicyScore.id.desc()))


def latest_regime(db: Session) -> MacroRegime | None:
    return db.scalar(select(MacroRegime).order_by(MacroRegime.as_of.desc(), MacroRegime.id.desc()))


def surprise_index(db: Session, country: str, days: int = 120) -> float | None:
    since = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(EconomicSurprise, Indicator)
        .join(Indicator, EconomicSurprise.indicator_id == Indicator.id)
        .where(Indicator.country == country, EconomicSurprise.created_at >= since)
    ).all()
    num = den = 0.0
    for s, ind in rows:
        if s.historical_z is None:
            continue
        sign = 1 if s.policy_direction == "Hawkish" else -1 if s.policy_direction == "Dovish" else 0
        w = IMPORTANCE_W.get(ind.importance, 0.5)
        num += sign * min(3.0, abs(s.historical_z)) * w
        den += w
    return round(num / den, 3) if den else None


def projection_deviations(db: Session, cb: CentralBank, snap: Snapshot | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    for ind in db.scalars(select(Indicator).where(Indicator.central_bank_code == cb.code,
                                                  Indicator.projection_variable.is_not(None))):
        if ind.projection_variable == "policy_rate":
            continue
        rel = da.latest_current(db, ind.id)
        if rel is None:
            continue
        pr = da.projection_for(db, cb.id, ind.projection_variable, rel.reference_period[:4])
        if pr is None:
            continue
        out[ind.projection_variable] = round(rel.actual - pr[0].value, 3)
        if snap is not None:
            _use(snap, rel, ind, False, f"{ind.name} vs projection")
    return out


def build(db: Session, currency: str) -> Snapshot:
    country = COUNTRY[currency]
    cb = da.cb_by_currency(db, currency)
    snap = Snapshot(currency, country, cb)
    if cb is not None:
        snap.inflation_target = cb.inflation_target
        ps = latest_policy_score(db, cb.id)
        if ps:
            snap.policy_score, snap.policy_confidence, snap.policy_components = ps.score, ps.confidence, ps.components
        rate_code = POLICY_RATE.get(cb.code)
        if rate_code:
            ind, rel = da.latest_by_code(db, rate_code)
            snap.policy_rate = _use(snap, rel, ind, True, "Policy rate")
            if rel is not None:
                hist = da.current_series(db, ind.id, 24)
                for a, b in zip(reversed(hist[:-1]), reversed(hist[1:])):
                    if abs(b.actual - a.actual) > 1e-6:
                        snap.last_decision = "HIKE" if b.actual > a.actual else "CUT"
                        snap.last_change_bps = round((b.actual - a.actual) * 100)
                        break
                else:
                    snap.last_decision = "HOLD"
        if snap.policy_rate is None:
            snap.policy_rate = cb.current_rate
            if cb.last_decision:
                snap.last_decision = cb.last_decision
                if cb.current_rate is not None and cb.previous_rate is not None:
                    snap.last_change_bps = round((cb.current_rate - cb.previous_rate) * 100)
        snap.deviations = projection_deviations(db, cb, snap)
        st = db.scalar(select(CentralBankStatement).where(CentralBankStatement.central_bank_id == cb.id,
                                                          CentralBankStatement.doc_type == "statement")
                       .order_by(CentralBankStatement.published_at.desc()))
        if st is not None:
            snap.statement_tone = st.tone_score
        rx = latest_rate_expectation(db, cb.code)
        if rx is not None:
            snap.prob_cut, snap.prob_hike = rx.prob_cut, rx.prob_hike
            snap.implied_change_bps = rx.implied_12m_change_bps
    ind_code = HEADLINE_INFL.get(country)
    if ind_code:
        ind, rel = da.latest_by_code(db, ind_code)
        snap.inflation = _use(snap, rel, ind, True, "Headline inflation")
    if country in UNEMP:
        ind, rel = da.latest_by_code(db, UNEMP[country])
        if rel is not None:
            _use(snap, rel, ind, False, "Unemployment")
            series = da.current_series(db, ind.id, 8)
            if len(series) >= 4:
                snap.unemployment_change_6m = round(series[-1].actual - series[max(0, len(series) - 7)].actual, 2)
    if country in GDP:
        ind, rel = da.latest_by_code(db, GDP[country])
        snap.gdp_latest = _use(snap, rel, ind, False, "GDP")
    if country in PMI:
        ind, rel = da.latest_by_code(db, PMI[country])
        snap.pmi = _use(snap, rel, ind, False, "PMI")
    yc = YIELD_COUNTRY[currency]
    y2 = latest_yield(db, yc, "2Y")
    y10 = latest_yield(db, yc, "10Y")
    snap.y2 = y2.yield_pct if y2 else None
    snap.y10 = y10.yield_pct if y10 else None
    if y2:
        old = latest_yield(db, yc, "2Y", before=y2.ts - timedelta(days=30))
        if old:
            snap.y2_change_1m_bps = round((y2.yield_pct - old.yield_pct) * 100, 1)
    if snap.implied_change_bps is None and snap.y2 is not None and snap.policy_rate is not None:
        snap.implied_change_bps = round((snap.y2 - snap.policy_rate) * 100)
        snap.implied_is_proxy = True
    snap.surprise_index = surprise_index(db, country)
    return snap


def build_all(db: Session) -> dict[str, Snapshot]:
    return {c: build(db, c) for c in CURRENCIES}
