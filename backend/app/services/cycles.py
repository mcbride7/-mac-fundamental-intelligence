"""Policy cycle divergence: which central banks are hiking, cutting or holding, whether the data supports it,
and the pairs where one bank's cycle runs against the other's.

Cycle (from the rate path, last 12 months):
  Hiking   - last move was a hike within ~9 months (and the market isn't pricing cuts)
  Cutting  - last move was a cut within ~9 months (and the market isn't pricing hikes)
  Holding  - no move for 9+ months, or a pause after a cycle
Data lean (-1 dovish .. +1 hawkish), averaged from what is available:
  inflation vs target, core inflation vs target, inflation trend (last 3 readings), jobs (unemployment
  trend), growth (GDP q/q and PMIs vs 50), and data surprises vs forecasts.
Support: hiking needs hawkish data, cutting needs dovish data, holding fits balanced data.
Divergence: two banks in different cycles; "confirmed" when the data backs both sides.
"""
from __future__ import annotations

import itertools
import statistics
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.engines import fundamentals as fnd
from app.models import CentralBank, CentralBankMeeting, Indicator
from app.services import data_access as da

BANKS = ["FED", "ECB", "BOE", "BOJ", "SNB", "BOC", "RBA", "RBNZ", "SARB", "BANXICO"]
CORE = {"US": "US_CORE_CPI_YOY", "EA": "EA_CORE_HICP_YOY", "GB": "GB_CORE_CPI_YOY", "JP": "JP_CORE_CPI_YOY",
        "CH": "CH_CORE_CPI_YOY", "CA": "CA_CORE_CPI_TRIM_YOY", "AU": "AU_CORE_TRIMMED_MEAN_YOY",
        "NZ": "NZ_CORE_CPI_YOY", "ZA": "ZA_CORE_CPI_YOY", "MX": "MX_CORE_CPI_YOY"}
UNEMP = {"US": "US_UNEMPLOYMENT", "EA": "EA_UNEMPLOYMENT", "GB": "GB_UNEMPLOYMENT", "JP": "JP_UNEMPLOYMENT",
         "CH": "CH_UNEMPLOYMENT", "CA": "CA_UNEMPLOYMENT", "AU": "AU_UNEMPLOYMENT", "NZ": "NZ_UNEMPLOYMENT"}
GDP_QOQ = {"US": "US_GDP_QOQ", "EA": "EA_GDP_QOQ", "GB": "GB_GDP_QOQ", "JP": "JP_GDP_QOQ", "CH": "CH_GDP_QOQ",
           "CA": "CA_GDP_MOM", "AU": "AU_GDP_QOQ", "NZ": "NZ_GDP_QOQ", "ZA": "ZA_GDP_QOQ"}
PMIS = {"US": ["US_ISM_MANUF", "US_ISM_SERVICES"], "EA": ["EA_PMI_COMPOSITE", "EA_MANUF_PMI", "EA_SERVICES_PMI"],
        "GB": ["GB_MANUF_PMI", "GB_SERVICES_PMI"], "JP": ["JP_MANUF_PMI", "JP_SERVICES_PMI"],
        "CH": ["CH_MANUF_PMI", "CH_SERVICES_PMI"], "CA": ["CA_IVEY_PMI", "CA_MANUF_PMI"],
        "AU": ["AU_MANUF_PMI", "AU_SERVICES_PMI"], "NZ": ["NZ_MANUF_PMI", "NZ_SERVICES_PMI"],
        "ZA": ["ZA_MANUF_PMI"], "MX": ["MX_MANUF_PMI"]}
ORDER = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY", "ZAR", "MXN"]


def _clip(x: float, lim: float = 1.0) -> float:
    return max(-lim, min(lim, x))


def _series(db: Session, code: str | None, n: int = 12) -> list:
    ind = da.indicator_by_code(db, code) if code else None
    return da.current_series(db, ind.id, n) if ind else []


def _period_date(p: str) -> date | None:
    try:
        if "Q" in p:
            return date(int(p[:4]), (int(p[-1]) - 1) * 3 + 3, 1)
        return date(int(p[:4]), int(p[5:7]), 1)
    except (ValueError, IndexError):
        return None


def moves(db: Session, cb: CentralBank) -> list[tuple[date, float]]:
    """Rate changes in basis points with their dates, newest last."""
    out: dict[date, float] = {}
    code = fnd.POLICY_RATE.get(cb.code)
    hist = _series(db, code, 30)
    for a, b in zip(hist, hist[1:]):
        if abs(b.actual - a.actual) > 1e-6 and (d := _period_date(b.reference_period)):
            out[d] = round((b.actual - a.actual) * 100)
    for m in db.scalars(select(CentralBankMeeting).where(CentralBankMeeting.central_bank_id == cb.id,
                                                         CentralBankMeeting.decision.is_not(None))):
        if m.decision in ("HIKE", "CUT"):
            bps = m.change_bps if m.change_bps else (25 if m.decision == "HIKE" else -25)
            # skip if the rate history already has this move in the same month
            if not any(abs((d - m.meeting_date).days) < 31 and (v > 0) == (bps > 0) for d, v in out.items()):
                out[m.meeting_date] = bps
    if not out and cb.last_decision in ("HIKE", "CUT") and cb.last_decision_date:
        out[cb.last_decision_date] = round(((cb.current_rate or 0) - (cb.previous_rate or 0)) * 100) or \
            (25 if cb.last_decision == "HIKE" else -25)
    return sorted(out.items())


def cycle(db: Session, cb: CentralBank, snap, today: date | None = None) -> dict:
    today = today or date.today()
    mv = moves(db, cb)
    year = [(d, v) for d, v in mv if d >= today - timedelta(days=365)]
    last = mv[-1] if mv else None
    hikes, cuts = sum(1 for _, v in year if v > 0), sum(1 for _, v in year if v < 0)
    total = sum(v for _, v in year)
    priced = snap.implied_change_bps
    if snap.prob_cut is not None and snap.prob_hike is not None and priced is None:
        priced = (snap.prob_hike - snap.prob_cut) / 2
    stage, label = "holding", "Holding"
    if last and (today - last[0]).days <= 270:
        recent = (today - last[0]).days <= 120
        if last[1] > 0:
            stage, label = "hiking", "Hiking" if recent else "Hiking (paused)"
        else:
            stage, label = "cutting", "Cutting" if recent else "Cutting (paused)"
    elif last:
        label = f"Holding since {'a hike' if last[1] > 0 else 'a cut'} in {last[0].strftime('%b %Y')}"
    expects = None
    if priced is not None:
        expects = ("more hikes priced" if priced >= 15 else "cuts priced" if priced <= -15 else "little change priced")
        expects += f" ({priced:+.0f} bp over 12 months)" if snap.implied_change_bps is not None else ""
    return {"stage": stage, "label": label, "hikes_12m": hikes, "cuts_12m": cuts, "change_12m_bps": total,
            "last_move": {"date": last[0].isoformat(), "bps": last[1]} if last else None,
            "market": expects, "priced_bps": priced}


def data_lean(db: Session, cb: CentralBank, snap) -> dict:
    country = cb.country
    parts: list[tuple[str, float, str]] = []
    tgt = cb.inflation_target
    if snap.inflation is not None and tgt is not None:
        gap = snap.inflation - tgt
        parts.append(("Inflation", _clip(gap / 1.0), f"{snap.inflation:.1f}% vs {tgt:g}% target"))
    core = _series(db, CORE.get(country), 6)
    if core and tgt is not None:
        gap = core[-1].actual - tgt
        parts.append(("Core inflation", _clip(gap / 1.0), f"{core[-1].actual:.1f}% vs {tgt:g}% target"))
    head = _series(db, fnd.HEADLINE_INFL.get(country), 6)
    if len(head) >= 4:
        ch = head[-1].actual - head[-4].actual
        parts.append(("Inflation trend", _clip(ch / 0.5), f"{'rising' if ch > 0.05 else 'falling' if ch < -0.05 else 'flat'} "
                      f"({ch:+.1f} pp over 3 readings)"))
    un = _series(db, UNEMP.get(country), 8)
    if len(un) >= 4:
        ch = un[-1].actual - un[max(0, len(un) - 7)].actual
        parts.append(("Jobs", _clip(-ch / 0.3), f"unemployment {un[-1].actual:.1f}%, {ch:+.1f} pp over ~6 months"))
    g = _series(db, GDP_QOQ.get(country), 3)
    if g:
        parts.append(("Growth", _clip((g[-1].actual - 0.3) / 0.4), f"GDP {g[-1].actual:+.1f}% ({g[-1].reference_period})"))
    pm = [s[-1].actual for code in PMIS.get(country, []) if (s := _series(db, code, 2))]
    if pm:
        avg = statistics.fmean(pm)
        parts.append(("PMIs", _clip((avg - 50) / 4), f"average {avg:.1f} ({'expansion' if avg > 50 else 'contraction'})"))
    if snap.surprise_index is not None:
        parts.append(("Data surprises", _clip(snap.surprise_index), "beating forecasts" if snap.surprise_index > 0.1
                      else "missing forecasts" if snap.surprise_index < -0.1 else "in line with forecasts"))
    if not parts:
        return {"score": None, "label": "No data", "signals": []}
    sc = round(statistics.fmean(v for _, v, _ in parts), 2)
    label = "Hawkish" if sc >= 0.25 else "Dovish" if sc <= -0.25 else "Balanced"
    return {"score": sc, "label": label,
            "signals": [{"name": n, "score": round(v, 2), "note": t} for n, v, t in parts]}


def support(stage: str, lean: dict) -> dict:
    sc = lean.get("score")
    if sc is None:
        return {"verdict": "Unknown", "supported": None, "note": "Not enough data yet to judge"}
    if stage == "hiking":
        if sc >= 0.25:
            return {"verdict": "Supported", "supported": True, "note": "Data is hawkish: hikes are justified"}
        if sc <= -0.25:
            return {"verdict": "Not supported", "supported": False, "note": "Data is dovish: the hiking cycle may be ending"}
        return {"verdict": "Partly", "supported": None, "note": "Data is mixed: a pause is likely"}
    if stage == "cutting":
        if sc <= -0.25:
            return {"verdict": "Supported", "supported": True, "note": "Data is dovish: cuts are justified"}
        if sc >= 0.25:
            return {"verdict": "Not supported", "supported": False, "note": "Data is hawkish: the cutting cycle may be ending"}
        return {"verdict": "Partly", "supported": None, "note": "Data is mixed: a pause is likely"}
    if sc >= 0.25:
        return {"verdict": "Hold, leaning to hike", "supported": True, "note": "Data is hawkish: next move more likely up"}
    if sc <= -0.25:
        return {"verdict": "Hold, leaning to cut", "supported": True, "note": "Data is dovish: next move more likely down"}
    return {"verdict": "Supported", "supported": True, "note": "Data is balanced: holding fits"}


def stance(stage: str, lean: dict, priced: float | None) -> float:
    """-1.5 (firmly easing) .. +1.5 (firmly tightening): the cycle, nudged by the data and by market pricing."""
    base = {"hiking": 1.0, "cutting": -1.0, "holding": 0.0}[stage]
    sc = lean.get("score") or 0.0
    pr = _clip((priced or 0) / 50) if priced is not None else 0.0
    return round(base + 0.35 * sc + 0.15 * pr, 2)


def board(db: Session, today: date | None = None) -> dict:
    banks = []
    for code in BANKS:
        cb = da.cb_by_code(db, code)
        if cb is None:
            continue
        snap = fnd.build(db, cb.currency)
        cy = cycle(db, cb, snap, today)
        lean = data_lean(db, cb, snap)
        sup = support(cy["stage"], lean)
        banks.append({"code": cb.code, "name": cb.short_name, "currency": cb.currency, "rate": snap.policy_rate,
                      "cycle": cy, "data": lean, "support": sup,
                      "stance": stance(cy["stage"], lean, cy["priced_bps"])})
    pairs = []
    for a, b in itertools.combinations(banks, 2):
        sa, sb = a["cycle"]["stage"], b["cycle"]["stage"]
        if sa == sb and not ({"Hold, leaning to hike", "Hold, leaning to cut"} == {a["support"]["verdict"], b["support"]["verdict"]}):
            continue
        hawk, dove = (a, b) if a["stance"] >= b["stance"] else (b, a)
        gap = round(hawk["stance"] - dove["stance"], 2)
        if gap < 0.6:
            continue
        both = hawk["support"]["supported"] is True and dove["support"]["supported"] is True
        any_against = hawk["support"]["supported"] is False or dove["support"]["supported"] is False
        kind = ("Hiking vs cutting" if {sa, sb} == {"hiking", "cutting"} else
                f"{hawk['cycle']['stage'].title()} vs {dove['cycle']['stage']}")
        x, y = hawk["currency"], dove["currency"]
        base, quote = (x, y) if ORDER.index(x) < ORDER.index(y) else (y, x)
        side = "Long" if base == x else "Short"
        strength = "Strong" if gap >= 1.6 and both else "Moderate" if gap >= 1.0 and not any_against else "Weak"
        pairs.append({"pair": f"{base}/{quote}", "trade": f"{side} {base}/{quote}", "kind": kind, "gap": gap,
                      "confirmed": both, "against": any_against, "strength": strength,
                      "hawk": {"code": hawk["code"], "currency": x, "cycle": hawk["cycle"]["label"],
                               "support": hawk["support"]["verdict"], "data": hawk["data"]["label"]},
                      "dove": {"code": dove["code"], "currency": y, "cycle": dove["cycle"]["label"],
                               "support": dove["support"]["verdict"], "data": dove["data"]["label"]},
                      "why": f"{hawk['name']} {hawk['cycle']['label'].lower()} ({hawk['support']['verdict'].lower()}) vs "
                             f"{dove['name']} {dove['cycle']['label'].lower()} ({dove['support']['verdict'].lower()})"})
    rank = {"Strong": 0, "Moderate": 1, "Weak": 2}
    pairs.sort(key=lambda p: (rank[p["strength"]], not p["confirmed"], -p["gap"]))
    return {"banks": banks, "pairs": pairs}
