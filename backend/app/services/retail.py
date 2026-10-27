"""Retail sentiment: Myfxbook Community Outlook (needs a free Myfxbook account) or values typed in.

Retail positioning is read contrarian: when most retail traders are long, the crowd is usually wrong
near turning points, so the setup score leans the other way.
"""
from __future__ import annotations

from datetime import timedelta

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import utcnow
from app.ingestion.base import SourceUnavailable
from app.models import RetailSentiment, Source

BASE = "https://www.myfxbook.com/api"
STALE_AFTER = timedelta(days=3)


def fetch_myfxbook() -> dict[str, float]:
    if not (settings.myfxbook_email and settings.myfxbook_password):
        raise SourceUnavailable("Set MYFXBOOK_EMAIL and MYFXBOOK_PASSWORD (a free Myfxbook account) on api and "
                                "worker, or type retail sentiment in on the Top setups page.")
    r = requests.get(f"{BASE}/login.json", params={"email": settings.myfxbook_email,
                                                   "password": settings.myfxbook_password}, timeout=30)
    data = r.json()
    if data.get("error"):
        raise SourceUnavailable(f"Myfxbook login failed: {data.get('message', 'check email and password')}")
    session = data["session"]
    try:
        r = requests.get(f"{BASE}/get-community-outlook.json", params={"session": session}, timeout=30)
        out = r.json()
        if out.get("error"):
            raise SourceUnavailable(f"Myfxbook: {out.get('message')}")
        result = {}
        for s in out.get("symbols", []):
            name = str(s.get("name", "")).upper().replace("/", "")
            lp = s.get("longPercentage")
            if name and lp is not None:
                result[name] = float(lp)
        return result
    finally:
        try:
            requests.get(f"{BASE}/logout.json", params={"session": session}, timeout=10)
        except requests.RequestException:
            pass


def run_myfxbook(db: Session, src: Source) -> int:
    if not (settings.myfxbook_email and settings.myfxbook_password):
        return 0  # not set up: retail sentiment can be typed in instead, so this isn't an error
    got = fetch_myfxbook()
    for sym, lp in got.items():
        db.add(RetailSentiment(symbol=sym, long_pct=lp, source="Myfxbook"))
    db.commit()
    return len(got)


def set_manual(db: Session, symbol: str, long_pct: float) -> RetailSentiment:
    if not 0 <= long_pct <= 100:
        raise ValueError("Long % must be between 0 and 100")
    row = RetailSentiment(symbol=symbol.upper().replace("/", ""), long_pct=long_pct, source="manual")
    db.add(row)
    db.commit()
    return row


def latest(db: Session, symbol: str) -> RetailSentiment | None:
    r = db.scalar(select(RetailSentiment).where(RetailSentiment.symbol == symbol)
                  .order_by(RetailSentiment.as_of.desc(), RetailSentiment.id.desc()))
    if r is None:
        return None
    as_of = r.as_of if r.as_of.tzinfo else r.as_of.replace(tzinfo=utcnow().tzinfo)
    return None if utcnow() - as_of > STALE_AFTER else r


def _aware(t):
    return t if t.tzinfo else t.replace(tzinfo=utcnow().tzinfo)


def board(db: Session, days: int = 30) -> dict:
    """Latest retail long % for every tracked symbol, the change over about a week, and a daily history."""
    from app.services.setups_table import CROSSES, EM, MAJORS

    symbols = MAJORS + CROSSES + EM + ["XAUUSD", "XAGUSD"]
    names = {"XAUUSD": "Gold", "XAGUSD": "Silver"}
    since = utcnow() - timedelta(days=days)
    rows = db.scalars(select(RetailSentiment).where(RetailSentiment.symbol.in_(symbols), RetailSentiment.as_of >= since)
                      .order_by(RetailSentiment.as_of, RetailSentiment.id)).all()
    by: dict[str, list[RetailSentiment]] = {}
    for r in rows:
        by.setdefault(r.symbol, []).append(r)
    out = []
    for s in symbols:
        hist = by.get(s, [])
        if not hist:
            out.append({"symbol": s, "name": names.get(s, f"{s[:3]}/{s[3:]}"), "long_pct": None, "history": []})
            continue
        last = hist[-1]
        daily: dict[str, float] = {}
        for r in hist:
            daily[_aware(r.as_of).date().isoformat()] = round(r.long_pct, 1)  # last reading of each day
        week_ago = [r for r in hist if _aware(r.as_of) <= _aware(last.as_of) - timedelta(days=6)]
        lp = round(last.long_pct, 1)
        stale = utcnow() - _aware(last.as_of) > STALE_AFTER
        read = ("Retail heavily long: contrarian bearish" if lp >= 70 else "Retail mostly long: leans bearish" if lp >= 60
                else "Retail heavily short: contrarian bullish" if lp <= 30 else "Retail mostly short: leans bullish" if lp <= 40
                else "Balanced: no edge")
        out.append({"symbol": s, "name": names.get(s, f"{s[:3]}/{s[3:]}"), "long_pct": lp, "short_pct": round(100 - lp, 1),
                    "change_week": round(lp - week_ago[-1].long_pct, 1) if week_ago else None,
                    "source": last.source, "as_of": _aware(last.as_of).isoformat(), "stale": stale, "read": read,
                    "history": [{"d": d, "long_pct": v} for d, v in daily.items()]})
    have = [x for x in out if x["long_pct"] is not None and not x["stale"]]
    return {"symbols": out, "live": len(have), "myfxbook": bool(settings.myfxbook_email and settings.myfxbook_password)}
