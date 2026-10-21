"""Click-to-edit for the numbers on a central bank's Overview.

Where each number lives decides how it is saved:
  current_rate      - banks with a policy-rate indicator (Fed, ECB, BoE, BoJ, SARB): saved as a release of that
                      indicator for the chosen month, through the checked manual-data path. Other banks: stored
                      on the bank itself, with the old rate becoming the previous rate and the decision worked out.
  previous_rate, last_decision, inflation_target - stored on the bank.
  next_meeting, expected_decision - stored on the next scheduled meeting (created if there is none).
  release           - any indicator value (inflation, GDP, the 'Data behind this page' list): saved as a release
                      for its period through the checked manual-data path.
Every change is audited and the bank is re-analysed.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.engines.fundamentals import POLICY_RATE
from app.models import CentralBank, CentralBankMeeting
from app.services import data_access as da
from app.services import manual_service as ms
from app.services import recompute
from app.services.audit import audit

FIELDS = ("current_rate", "previous_rate", "last_decision", "inflation_target", "next_meeting",
          "expected_decision", "release")
DECISIONS = ("HIKE", "CUT", "HOLD")


def _number(value, label: str, lo: float, hi: float) -> float:
    try:
        v = float(str(value).replace("%", "").replace(",", ".").strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label}: type a number, like 4.25") from None
    if not lo <= v <= hi:
        raise ValueError(f"{label} must be between {lo:g} and {hi:g}")
    return v


def _decision(value) -> str:
    v = str(value or "").strip().upper()
    if v not in DECISIONS:
        raise ValueError("Choose HIKE, CUT or HOLD")
    return v


def _period_ok(period: str | None, frequency: str) -> str:
    p = (period or "").strip().upper()
    if frequency == "quarterly" and re.fullmatch(r"\d{4}Q[1-4]", p):
        return p
    if frequency != "quarterly" and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", p):
        return p
    raise ValueError("Period should look like 2026Q3" if frequency == "quarterly" else "Period should look like 2026-09")


def has_rate_indicator(cb: CentralBank) -> bool:
    return cb.code in POLICY_RATE


def edit(db: Session, cb: CentralBank, field: str, value, period: str | None = None,
         indicator_code: str | None = None, reason: str | None = None, user_id: int | None = None) -> dict:
    if field not in FIELDS:
        raise ValueError(f"Field must be one of {', '.join(FIELDS)}")
    out: dict = {"field": field}

    if field == "release" or (field == "current_rate" and has_rate_indicator(cb)):
        code = POLICY_RATE[cb.code] if field == "current_rate" else (indicator_code or "")
        ind = da.indicator_by_code(db, code)
        if ind is None:
            raise LookupError(f"Unknown indicator {code}")
        v = _number(value, ind.name, -1000, 1_000_000)
        per = period or (utcnow().strftime("%Y-%m") if field == "current_rate" else None)
        per = _period_ok(per, ind.frequency)
        # the value for the period before, so the usual jump checks can run
        earlier = [r for r in da.current_series(db, ind.id, 36) if r.reference_period < per]
        res = ms.quick_release(db, ind, per, v, user_id, reason, "Central bank page edit", "cb_overview_edit",
                               previous=earlier[-1].actual if earlier else None)
        return out | {"value": v, "period": per, "indicator_code": ind.code, **res}

    before = None
    if field == "current_rate":
        v = _number(value, "Rate", -5, 100)
        before = cb.current_rate
        if before is None or abs(v - before) > 1e-9:
            cb.previous_rate = before
            cb.current_rate = v
            cb.last_decision = "HOLD" if before is None else ("HIKE" if v > before else "CUT")
            cb.last_decision_date = date.today()
        out["value"] = v
    elif field == "previous_rate":
        if has_rate_indicator(cb):
            raise ValueError(f"The {cb.short_name}'s previous rate comes from its rate history. "
                             "Edit the current rate for the month it changed instead.")
        before, cb.previous_rate = cb.previous_rate, _number(value, "Previous rate", -5, 100)
        out["value"] = cb.previous_rate
    elif field == "last_decision":
        if has_rate_indicator(cb):
            raise ValueError(f"The {cb.short_name}'s last decision is worked out from its rate history. "
                             "Edit the current rate instead.")
        before, cb.last_decision = cb.last_decision, _decision(value)
        cb.last_decision_date = date.today()
        out["value"] = cb.last_decision
    elif field == "inflation_target":
        before, cb.inflation_target = cb.inflation_target, _number(value, "Inflation target", -5, 50)
        out["value"] = cb.inflation_target
    else:  # next meeting fields
        today = utcnow().date()
        m = db.scalar(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id,
                                                       CentralBankMeeting.meeting_date >= today)
                      .order_by(CentralBankMeeting.meeting_date))
        if field == "next_meeting":
            try:
                d = date.fromisoformat(str(value).strip())
            except ValueError:
                raise ValueError("Pick a date") from None
            if d < today:
                raise ValueError("The next meeting can't be in the past. Record past decisions under Policy.")
            if m is None:
                m = CentralBankMeeting(central_bank_id=cb.id, meeting_date=d)
                db.add(m)
            else:
                before, m.meeting_date = m.meeting_date.isoformat(), d
            out["value"] = d.isoformat()
        else:
            if m is None:
                raise ValueError("Set the next meeting date first")
            v = None if value in (None, "") else _decision(value)
            before, m.expected_decision = m.expected_decision, v
            out["value"] = v
    audit(db, "central_bank", cb.id, f"edited {field}", user_id, before=before, after=out.get("value"),
          reason=reason)
    db.commit()
    job = recompute.trigger(db, "central_bank", cb.id, central_banks={cb.code}, currencies={cb.currency})
    return out | {"recompute": job.summary}
