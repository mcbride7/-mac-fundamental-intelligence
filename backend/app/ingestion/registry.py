"""Registry of automated jobs and official-value fetchers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion import central_banks, fred, markets
from app.ingestion.base import run_source

JOBS = {
    "fred": fred.run_fred,
    "fed_rss": central_banks.runner(central_banks.FEEDS[0]),
    "ecb_rss": central_banks.runner(central_banks.FEEDS[1]),
    "boe_rss": central_banks.runner(central_banks.FEEDS[2]),
    "twelvedata": markets.run_prices,
    "finnhub": markets.run_finnhub,
}


def run(db: Session, key: str) -> dict:
    return run_source(db, key, JOBS[key])


def run_all(db: Session) -> list[dict]:
    return [run(db, k) for k in JOBS]


def official_fetchers() -> dict:
    """source key -> fetch(indicator, period). Used by background verification."""
    out = {}
    if settings.fred_api_key:
        out["fred"] = fred.official_value
        out["bls"] = fred.official_value
        out["bea"] = fred.official_value
    return out
