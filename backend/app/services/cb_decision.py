"""Turn a new decision statement into the bank's 'last decision' (and new rate) on its Overview."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.decision import parse_decision
from app.models import CentralBank, CentralBankMeeting, CentralBankStatement


def record_from_statement(db: Session, st: CentralBankStatement) -> dict | None:
    if st is None or (st.doc_type or "statement") != "statement":
        return None
    cb = db.get(CentralBank, st.central_bank_id)
    when: date = st.meeting_date or (st.published_at.date() if st.published_at else date.today())
    if cb.last_decision_date and cb.last_decision_date > when:
        return None  # an older statement: keep the newer decision
    decision, rate = parse_decision(st.text or "", cb.code)
    if decision is None:
        return None
    from app.engines import fundamentals as fnd

    before = fnd.build(db, cb.currency).policy_rate
    if decision == "HOLD" and rate is None:
        rate = before
    m = db.scalar(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id,
                                                   CentralBankMeeting.meeting_date == when))
    if m is None:
        m = CentralBankMeeting(central_bank_id=cb.id, meeting_date=when)
        db.add(m)
    m.decision = decision
    if before is not None:
        m.rate_before = before
    if rate is not None:
        m.rate_after = rate
    if m.rate_before is not None and m.rate_after is not None:
        m.change_bps = round((m.rate_after - m.rate_before) * 100)
    cb.last_decision, cb.last_decision_date = decision, when
    if rate is not None and (cb.current_rate is None or abs(rate - (cb.current_rate or 0)) > 1e-9 or decision == "HOLD"):
        if decision != "HOLD":
            cb.previous_rate = before if before is not None else cb.current_rate
        cb.current_rate = rate
    db.commit()
    return {"decision": decision, "rate": rate, "date": when.isoformat()}


def backfill(db: Session) -> int:
    """Latest decision statement of every bank -> its last decision (used at start-up, harmless to repeat)."""
    n = 0
    for cb in db.scalars(select(CentralBank)):
        st = db.scalar(select(CentralBankStatement).where(CentralBankStatement.central_bank_id == cb.id,
                                                          CentralBankStatement.doc_type == "statement")
                       .order_by(CentralBankStatement.published_at.desc()))
        if st is not None and record_from_statement(db, st):
            n += 1
    return n


def characterise_latest(db: Session, cb: CentralBank, snap) -> dict | None:
    """Hawkish / dovish hold (or cut / hike) for the bank's latest decision, with the reasons."""
    from app.analytics.decision import characterise, parse_dissent
    from app.engines import fundamentals as fnd

    decision = snap.last_decision
    if decision is None:
        return None
    sts = list(db.scalars(select(CentralBankStatement).where(CentralBankStatement.central_bank_id == cb.id,
                                                             CentralBankStatement.doc_type == "statement")
                          .order_by(CentralBankStatement.published_at.desc()).limit(2)))
    st = sts[0] if sts else None
    when = snap.last_decision_date
    # only use the statement if it belongs to this decision (same week)
    if st is not None and when is not None and st.published_at is not None:
        if abs((st.published_at.date() - when).days) > 6:
            st = None
    prev = sts[1] if st is not None and len(sts) > 1 else None
    meeting = None
    if when is not None:
        meeting = db.scalar(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id,
                                                             CentralBankMeeting.meeting_date == when))
    before = st.published_at if st is not None else None
    rx = fnd.latest_rate_expectation(db, cb.code, before=before) if before is not None else None
    res = characterise(decision, st.tone_score if st else None, prev.tone_score if prev else None,
                       parse_dissent(st.text) if st else None,
                       expected=meeting.expected_decision if meeting else None,
                       prob_cut=rx.prob_cut if rx else None, prob_hike=rx.prob_hike if rx else None,
                       inflation=snap.inflation, target=cb.inflation_target)
    if res is not None and st is None:
        res["reasons"].insert(0, "No decision statement stored for this meeting: fetch it for a fuller read")
    return res
