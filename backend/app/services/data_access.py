"""Common read queries shared by services and engines."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.enums import VerificationStatus
from app.models import (
    CentralBank,
    CentralBankProjection,
    EconomicEvent,
    EconomicRelease,
    Indicator,
    ProjectionVintage,
)
from app.services.extraction.normalizer import IndicatorRef

USABLE = (VerificationStatus.VERIFIED.value, VerificationStatus.USER_CONFIRMED.value,
          VerificationStatus.UNVERIFIED.value, VerificationStatus.CONFLICT.value)


def indicator_refs(db: Session) -> list[IndicatorRef]:
    return [IndicatorRef(i.code, i.name, i.country, i.currency, i.unit, i.transform, i.aliases or [])
            for i in db.scalars(select(Indicator))]


def indicator_by_code(db: Session, code: str) -> Indicator | None:
    return db.scalar(select(Indicator).where(Indicator.code == code))


def cb_by_code(db: Session, code: str) -> CentralBank | None:
    return db.scalar(select(CentralBank).where(CentralBank.code == code.upper()))


def cb_by_currency(db: Session, ccy: str) -> CentralBank | None:
    return db.scalar(select(CentralBank).where(CentralBank.currency == ccy.upper()))


def current_release(db: Session, indicator_id: int, period: str) -> EconomicRelease | None:
    return db.scalar(
        select(EconomicRelease)
        .where(EconomicRelease.indicator_id == indicator_id, EconomicRelease.reference_period == period,
               EconomicRelease.is_current.is_(True))
        .order_by(EconomicRelease.id.desc())
    )


def releases_for_period(db: Session, indicator_id: int, period: str) -> list[EconomicRelease]:
    return list(db.scalars(
        select(EconomicRelease)
        .where(EconomicRelease.indicator_id == indicator_id, EconomicRelease.reference_period == period)
        .order_by(EconomicRelease.id)
    ))


def first_release(db: Session, indicator_id: int, period: str) -> EconomicRelease | None:
    """The initial print (real-time basis)."""
    # lowest revision number = initial print; within the same revision, the latest row is a
    # correction of a mistyped value, so prefer it. Conflicting values are never "first prints".
    return db.scalar(
        select(EconomicRelease)
        .where(EconomicRelease.indicator_id == indicator_id, EconomicRelease.reference_period == period,
               EconomicRelease.verification_status != VerificationStatus.CONFLICT.value)
        .order_by(EconomicRelease.revision_number, EconomicRelease.id.desc())
    )


def current_series(db: Session, indicator_id: int, limit: int = 60) -> list[EconomicRelease]:
    rows = list(db.scalars(
        select(EconomicRelease)
        .where(EconomicRelease.indicator_id == indicator_id, EconomicRelease.is_current.is_(True))
        .order_by(EconomicRelease.reference_period.desc())
        .limit(limit)
    ))
    return list(reversed(rows))


def latest_current(db: Session, indicator_id: int) -> EconomicRelease | None:
    return db.scalar(
        select(EconomicRelease)
        .where(EconomicRelease.indicator_id == indicator_id, EconomicRelease.is_current.is_(True))
        .order_by(EconomicRelease.reference_period.desc(), EconomicRelease.id.desc())
    )


def latest_by_code(db: Session, code: str) -> tuple[Indicator | None, EconomicRelease | None]:
    ind = indicator_by_code(db, code)
    return ind, (latest_current(db, ind.id) if ind else None)


def event_for(db: Session, indicator_id: int, period: str) -> EconomicEvent | None:
    return db.scalar(select(EconomicEvent).where(EconomicEvent.indicator_id == indicator_id,
                                                 EconomicEvent.reference_period == period))


def projection_for(db: Session, cb_id: int, variable: str, target_period: str,
                   as_of: date | datetime | None = None) -> tuple[CentralBankProjection, ProjectionVintage] | None:
    """Latest projection for (variable, target year) published on or before `as_of`
    — i.e. what the central bank knew at the time (forecast vintage system)."""
    q = (select(CentralBankProjection, ProjectionVintage)
         .join(ProjectionVintage, CentralBankProjection.vintage_id == ProjectionVintage.id)
         .where(and_(CentralBankProjection.central_bank_id == cb_id, CentralBankProjection.variable == variable,
                     CentralBankProjection.target_period == target_period)))
    if as_of is not None:
        d = as_of.date() if isinstance(as_of, datetime) else as_of
        q = q.where(ProjectionVintage.vintage_date <= d)
    row = db.execute(q.order_by(ProjectionVintage.vintage_date.desc())).first()
    return (row[0], row[1]) if row else None


def period_year(period: str) -> str:
    return period[:4]
