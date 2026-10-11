"""Load clearly-labelled DEMO data so you can explore every screen before connecting
real feeds. Every value is stored as UNVERIFIED manual data with source "DEMO".

    python -m scripts.demo_data          # load
    python -m scripts.demo_data --wipe   # delete everything first (DANGER: wipes the database)

Do not use demo values for any decision."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

from app.db import Base, SessionLocal, engine, init_db
from app.models import (
    BondYield,
    CentralBankMeeting,
    CentralBankProjection,
    CentralBankStatement,
    EconomicEvent,
    EconomicRelease,
    Indicator,
    MarketPrice,
    ProjectionVintage,
    RateExpectation,
)
from app.seed import seed
from app.services import data_access as da
from app.services import recompute

NOW = datetime.now(timezone.utc)

# indicator -> list of (period, actual, consensus)
SERIES = {
    "US_CPI_YOY": [("2026-04", 2.9, 2.9), ("2026-05", 3.0, 2.9), ("2026-06", 3.1, 3.0), ("2026-07", 3.2, 3.1),
                   ("2026-08", 3.2, 3.2), ("2026-09", 3.4, 3.1)],
    "US_CORE_PCE_YOY": [("2026-06", 2.8, 2.8), ("2026-07", 2.9, 2.8), ("2026-08", 3.0, 2.9)],
    "US_UNEMPLOYMENT": [("2026-04", 4.2, 4.2), ("2026-05", 4.2, 4.2), ("2026-06", 4.1, 4.2), ("2026-07", 4.1, 4.1),
                        ("2026-08", 4.0, 4.1), ("2026-09", 4.0, 4.1)],
    "US_ISM_MANUF": [("2026-09", 51.2, 49.8)],
    "EA_HICP_YOY": [("2026-04", 2.2, 2.2), ("2026-05", 2.1, 2.1), ("2026-06", 2.0, 2.0), ("2026-07", 1.9, 2.0),
                    ("2026-08", 1.9, 1.9), ("2026-09", 1.7, 1.9)],
    "EA_UNEMPLOYMENT": [("2026-04", 6.3, 6.3), ("2026-07", 6.4, 6.3), ("2026-09", 6.5, 6.4)],
    "EA_PMI_COMPOSITE": [("2026-09", 48.6, 49.5)],
    "GB_CPI_YOY": [("2026-07", 3.6, 3.5), ("2026-08", 3.7, 3.6), ("2026-09", 3.8, 3.7)],
    "JP_CPI_YOY": [("2026-08", 2.6, 2.7), ("2026-09", 2.5, 2.6)],
    "ZA_CPI_YOY": [("2026-07", 3.9, 3.8), ("2026-08", 3.6, 3.7), ("2026-09", 3.4, 3.6)],
    "US_FED_RATE": [("2026-07", 4.5, None), ("2026-09", 4.5, None)],
    "EA_ECB_RATE": [("2026-07", 2.25, None), ("2026-09", 2.0, None)],
    "GB_BOE_RATE": [("2026-08", 4.0, None), ("2026-09", 4.0, None)],
    "JP_BOJ_RATE": [("2026-09", 0.5, None)],
    "ZA_SARB_RATE": [("2026-07", 7.25, None), ("2026-09", 7.0, None)],
}

FED_PREV = ("Recent indicators suggest that economic activity has continued to expand at a solid pace. Job gains "
            "have slowed, and the unemployment rate has moved up but remains low. Inflation has moderated but remains "
            "somewhat elevated. The Committee decided to maintain the target range for the federal funds rate at "
            "4-1/4 to 4-1/2 percent. The Committee will carefully assess incoming data, the evolving outlook, and the "
            "balance of risks.")
FED_NEW = ("Recent indicators suggest that economic activity has continued to expand at a solid pace. Job gains have "
           "remained strong, and the unemployment rate has remained low. Inflation remains elevated. The Committee "
           "decided to maintain the target range for the federal funds rate at 4-1/4 to 4-1/2 percent. The Committee "
           "is highly attentive to inflation risks and does not expect it will be appropriate to reduce the target "
           "range until it has gained greater confidence that inflation is moving sustainably toward 2 percent.")
ECB_PREV = ("The Governing Council today decided to keep the three key ECB interest rates unchanged. Inflation is "
            "currently at around the 2% medium-term target. The Governing Council is determined to ensure that "
            "inflation stabilises sustainably at its 2% medium-term target.")
ECB_NEW = ("The Governing Council today decided to lower the three key ECB interest rates by 25 basis points. "
           "Inflation has eased further and is now below the 2% medium-term target. Growth has weakened and downside "
           "risks to the outlook have increased. The Governing Council will follow a data-dependent approach and "
           "stands ready to adjust all of its instruments.")


def run(wipe: bool = False) -> None:
    if wipe:
        Base.metadata.drop_all(engine)
    init_db()
    db = SessionLocal()
    seed(db)
    for code, rows in SERIES.items():
        ind = db.query(Indicator).filter_by(code=code).one()
        for i, (period, actual, cons) in enumerate(rows):
            if da.current_release(db, ind.id, period):
                continue
            ev = da.event_for(db, ind.id, period) or EconomicEvent(indicator_id=ind.id, reference_period=period,
                                                                    importance=ind.importance, consensus=cons)
            db.add(ev)
            db.flush()
            y, m = int(period[:4]), int(period[5:7])
            released = datetime(y + (m == 12), m % 12 + 1, 12, 12, 30, tzinfo=timezone.utc)
            db.add(EconomicRelease(event_id=ev.id, indicator_id=ind.id, reference_period=period, actual=actual,
                                   consensus=cons, previous=rows[i - 1][1] if i else None, unit=ind.unit,
                                   released_at=released, source_name="DEMO", input_method="typed",
                                   verification_status="UNVERIFIED"))
    upcoming = [("US_NFP", "2026-10", 6, 120.0), ("US_CPI_YOY", "2026-10", 9, 3.3), ("EA_HICP_YOY", "2026-10", 12, 1.7),
                ("GB_CPI_YOY", "2026-10", 13, 3.7)]
    for code, period, days, cons in upcoming:
        ind = db.query(Indicator).filter_by(code=code).one()
        if not da.event_for(db, ind.id, period):
            db.add(EconomicEvent(indicator_id=ind.id, reference_period=period, importance=ind.importance,
                                 consensus=cons, scheduled_at=NOW + timedelta(days=days)))
    for code, label, vd, vals in (
        ("FED", "June 2026 SEP (demo)", date(2026, 6, 17), {"inflation": 2.6, "core_inflation": 2.8, "unemployment": 4.4, "gdp": 1.8}),
        ("FED", "September 2026 SEP (demo)", date(2026, 9, 16), {"inflation": 2.9, "core_inflation": 3.0, "unemployment": 4.3, "gdp": 1.5}),
        ("ECB", "September 2026 staff projections (demo)", date(2026, 9, 11), {"inflation": 2.0, "core_inflation": 2.1, "unemployment": 6.3, "gdp": 0.9}),
    ):
        cb = da.cb_by_code(db, code)
        if db.query(ProjectionVintage).filter_by(label=label).first():
            continue
        v = ProjectionVintage(central_bank_id=cb.id, vintage_date=vd, label=label, input_method="typed",
                              verification_status="UNVERIFIED")
        db.add(v)
        db.flush()
        for var, val in vals.items():
            db.add(CentralBankProjection(vintage_id=v.id, central_bank_id=cb.id, variable=var, target_period="2026",
                                         value=val))
    for code, prev, new, d1, d2 in (("FED", FED_PREV, FED_NEW, date(2026, 7, 29), date(2026, 9, 16)),
                                    ("ECB", ECB_PREV, ECB_NEW, date(2026, 7, 24), date(2026, 9, 11))):
        cb = da.cb_by_code(db, code)
        if db.query(CentralBankStatement).filter_by(central_bank_id=cb.id).count():
            continue
        for txt, d in ((prev, d1), (new, d2)):
            db.add(CentralBankStatement(central_bank_id=cb.id, title=f"{cb.short_name} statement {d:%B %Y} (demo)",
                                        published_at=datetime(d.year, d.month, d.day, 18, tzinfo=timezone.utc),
                                        meeting_date=d, text=txt, input_method="typed",
                                        verification_status="UNVERIFIED"))
    for code, d, dec, before, after, exp in (("FED", date(2026, 9, 16), "HOLD", 4.5, 4.5, "CUT"),
                                             ("ECB", date(2026, 9, 11), "CUT", 2.25, 2.0, "CUT")):
        cb = da.cb_by_code(db, code)
        if not db.query(CentralBankMeeting).filter_by(central_bank_id=cb.id, meeting_date=d).first():
            db.add(CentralBankMeeting(central_bank_id=cb.id, meeting_date=d, decision=dec, rate_before=before,
                                      rate_after=after, change_bps=round((after - before) * 100), expected_decision=exp,
                                      expected_change_bps=-25, expected_tone=-20))
    for code, nxt in (("FED", 28), ("ECB", 20), ("BOE", 35)):
        cb = da.cb_by_code(db, code)
        d = (NOW + timedelta(days=nxt)).date()
        if not db.query(CentralBankMeeting).filter_by(central_bank_id=cb.id, meeting_date=d).first():
            db.add(CentralBankMeeting(central_bank_id=cb.id, meeting_date=d, expected_decision="HOLD"))
    for code, cut, hold, hike, impl in (("FED", 20, 70, 10, -25), ("ECB", 55, 45, 0, -50), ("BOE", 25, 70, 5, -40),
                                        ("BOJ", 0, 70, 30, 25)):
        db.add(RateExpectation(central_bank_code=code, ts=NOW - timedelta(days=1), prob_cut=cut, prob_hold=hold,
                               prob_hike=hike, implied_12m_change_bps=impl, source="DEMO", input_method="typed"))
    for c, y2, y10 in (("US", 4.30, 4.45), ("DE", 1.95, 2.55), ("GB", 3.95, 4.50), ("JP", 0.85, 1.55),
                       ("ZA", 7.40, 9.90)):
        for days, bump in ((35, -0.15), (0, 0.0)):
            ts = NOW - timedelta(days=days)
            db.merge(BondYield(country=c, tenor="2Y", ts=ts, yield_pct=y2 + bump, source="DEMO", input_method="typed"))
            db.merge(BondYield(country=c, tenor="10Y", ts=ts, yield_pct=y10 + bump / 2, source="DEMO",
                               input_method="typed"))
    for sym, p0, p1, cls in (("EURUSD", 1.112, 1.084, "fx"), ("GBPUSD", 1.301, 1.288, "fx"), ("USDJPY", 147.2, 149.8, "fx"),
                             ("USDZAR", 17.9, 18.3, "fx"), ("XAUUSD", 2610, 2655, "commodity"), ("SPX", 6450, 6520, "equity")):
        for days, p in ((30, p0), (0, p1)):
            db.merge(MarketPrice(symbol=sym, ts=NOW - timedelta(days=days), price=p, asset_class=cls, source="DEMO",
                                 input_method="typed", verification_status="UNVERIFIED"))
    db.commit()
    job = recompute.trigger(db, "full", None)
    print(job.summary.get("message"))
    if job.summary.get("failed"):
        print("Failed nodes:", job.summary["failed"])
    db.close()


if __name__ == "__main__":
    run(wipe="--wipe" in sys.argv)
