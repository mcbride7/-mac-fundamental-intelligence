"""Central-bank APIs (Sections 5-13, 16-27, 56)."""
from __future__ import annotations

from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Auth, current_user_id, get_db, row, rows
from app.engines import cb_engine
from app.engines.forecast_engine import accuracy_summary, where_are_we
from app.models import (
    CentralBank,
    CentralBankMeeting,
    CentralBankProjection,
    CentralBankSpeech,
    CentralBankStatement,
    ForecastRevision,
    PolicyScore,
    ProjectionVintage,
)
from app.services import data_access as da
from app.services import recompute
from app.services.audit import audit
from app.services.storage import sha256

router = APIRouter(prefix="/api/central-banks", tags=["central banks"], dependencies=[Auth])


def _cb(db: Session, cb_id: str) -> CentralBank:
    cb = da.cb_by_code(db, cb_id) if not cb_id.isdigit() else db.get(CentralBank, int(cb_id))
    if cb is None:
        raise HTTPException(404, "Unknown central bank")
    return cb


class StatementIn(BaseModel):
    text: str
    title: str | None = None
    published_date: date | None = None
    doc_type: str = "statement"
    url: str | None = None


class ProjectionRow(BaseModel):
    variable: str
    target_period: str
    value: float
    range_low: float | None = None
    range_high: float | None = None


class VintageIn(BaseModel):
    vintage_date: date
    label: str | None = None
    source_url: str | None = None
    projections: list[ProjectionRow]


class MeetingIn(BaseModel):
    meeting_date: date
    decision: str | None = None
    rate_before: float | None = None
    rate_after: float | None = None
    expected_decision: str | None = None
    expected_change_bps: float | None = None
    expected_tone: float | None = None
    expected_wording: str | None = None
    economist_consensus: str | None = None
    votes: dict | None = None


@router.get("")
def list_banks(db: Session = Depends(get_db)):
    return cb_engine.heatmap(db)


@router.get("/{cb_id}")
def dashboard(cb_id: str, db: Session = Depends(get_db)):
    return cb_engine.dashboard(db, _cb(db, cb_id))


@router.get("/{cb_id}/policy-history")
def policy_history(cb_id: str, limit: int = 100, db: Session = Depends(get_db)):
    cb = _cb(db, cb_id)
    return rows(db.scalars(select(PolicyScore).where(PolicyScore.central_bank_id == cb.id)
                           .order_by(PolicyScore.as_of.desc()).limit(limit)))


@router.get("/{cb_id}/statements")
def statements(cb_id: str, db: Session = Depends(get_db)):
    cb = _cb(db, cb_id)
    out = []
    for s in db.scalars(select(CentralBankStatement).where(CentralBankStatement.central_bank_id == cb.id)
                        .order_by(CentralBankStatement.published_at.desc())):
        d = row(s)
        d["text"] = s.text[:1500]
        out.append(d)
    return out


@router.post("/{cb_id}/statements")
def add_statement(cb_id: str, body: StatementIn, db: Session = Depends(get_db),
                  user_id: int = Depends(current_user_id)):
    """Add a statement by pasting its text (it is stored as UNVERIFIED manual data)."""
    cb = _cb(db, cb_id)
    pub = datetime.combine(body.published_date or date.today(), time(12), tzinfo=timezone.utc)
    st = CentralBankStatement(central_bank_id=cb.id, doc_type=body.doc_type,
                              title=body.title or f"{cb.short_name} {body.doc_type}", published_at=pub,
                              meeting_date=pub.date(), text=body.text, url=body.url,
                              sha256=sha256(body.text.encode()), input_method="typed",
                              verification_status="UNVERIFIED")
    db.add(st)
    db.commit()
    audit(db, "cb_statement", st.id, "added", user_id)
    job = recompute.trigger(db, "statement", st.id, central_banks={cb.code}, currencies={cb.currency},
                            statement_ids={st.id})
    return {"id": st.id, "recompute": job.summary}


@router.get("/{cb_id}/statement-comparison")
def statement_comparison(cb_id: str, statement_id: int | None = None, db: Session = Depends(get_db)):
    # null (not an error) when fewer than two statements are stored yet
    return cb_engine.comparison(db, _cb(db, cb_id), statement_id)


@router.get("/{cb_id}/speeches")
def speeches(cb_id: str, db: Session = Depends(get_db)):
    cb = _cb(db, cb_id)
    return [{**row(s), "text": (s.text or "")[:800]} for s in db.scalars(
        select(CentralBankSpeech).where(CentralBankSpeech.central_bank_id == cb.id)
        .order_by(CentralBankSpeech.delivered_at.desc()).limit(50))]


@router.get("/{cb_id}/projections")
def projections(cb_id: str, db: Session = Depends(get_db)):
    cb = _cb(db, cb_id)
    out = []
    for v in db.scalars(select(ProjectionVintage).where(ProjectionVintage.central_bank_id == cb.id)
                        .order_by(ProjectionVintage.vintage_date.desc())):
        out.append({**row(v), "projections": rows(db.scalars(
            select(CentralBankProjection).where(CentralBankProjection.vintage_id == v.id)))})
    revisions = rows(db.scalars(select(ForecastRevision).where(ForecastRevision.central_bank_id == cb.id)))
    return {"vintages": out, "revisions": revisions, "publishes": cb.publishes}


@router.post("/{cb_id}/projections")
def add_vintage(cb_id: str, body: VintageIn, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    """Store a projection round as a NEW vintage (old vintages are never overwritten)."""
    cb = _cb(db, cb_id)
    v = ProjectionVintage(central_bank_id=cb.id, vintage_date=body.vintage_date,
                          label=body.label or f"{cb.short_name} projections {body.vintage_date:%B %Y}",
                          source_url=body.source_url, input_method="typed", verification_status="UNVERIFIED")
    db.add(v)
    db.flush()
    for p in body.projections:
        db.add(CentralBankProjection(vintage_id=v.id, central_bank_id=cb.id, **p.model_dump()))
    db.commit()
    audit(db, "projection_vintage", v.id, "added", user_id, n=len(body.projections))
    job = recompute.trigger(db, "projection_vintage", v.id, central_banks={cb.code}, currencies={cb.currency})
    return {"id": v.id, "recompute": job.summary}


@router.get("/{cb_id}/forecast-accuracy")
def forecast_accuracy(cb_id: str, variable: str | None = None, basis: str = "real_time", window: str = "last8",
                      db: Session = Depends(get_db)):
    return accuracy_summary(db, _cb(db, cb_id).code, variable, basis, window)


@router.get("/{cb_id}/where-are-we")
def where(cb_id: str, db: Session = Depends(get_db)):
    return where_are_we(db, _cb(db, cb_id).code)


@router.get("/{cb_id}/meetings")
def meetings(cb_id: str, db: Session = Depends(get_db)):
    cb = _cb(db, cb_id)
    return rows(db.scalars(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id)
                           .order_by(CentralBankMeeting.meeting_date.desc())))


@router.post("/{cb_id}/meetings")
def add_meeting(cb_id: str, body: MeetingIn, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    """Record a scheduled meeting (with pre-meeting market expectations) or a decision."""
    cb = _cb(db, cb_id)
    m = db.scalar(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id,
                                                   CentralBankMeeting.meeting_date == body.meeting_date))
    if m is None:
        m = CentralBankMeeting(central_bank_id=cb.id, meeting_date=body.meeting_date)
        db.add(m)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    if body.rate_before is not None and body.rate_after is not None:
        m.change_bps = round((body.rate_after - body.rate_before) * 100)
    if body.decision and body.rate_after is not None:
        cb.previous_rate, cb.current_rate = body.rate_before, body.rate_after
        cb.last_decision, cb.last_decision_date = body.decision.upper(), body.meeting_date
    db.commit()
    audit(db, "cb_meeting", m.id, "saved", user_id)
    job = recompute.trigger(db, "meeting", m.id, central_banks={cb.code}, currencies={cb.currency}) \
        if body.decision else None
    return {"id": m.id, "recompute": job.summary if job else None}
