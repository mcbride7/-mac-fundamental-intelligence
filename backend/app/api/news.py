"""News tab: tagged headlines from central banks and FX news feeds."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import Auth, get_db
from app.services import news

router = APIRouter(prefix="/api/news", tags=["news"], dependencies=[Auth])


@router.get("")
def news_list(currency: str | None = None, topic: str | None = None, tone: str | None = None,
              kind: str | None = None, q: str | None = None, days: int = 7, limit: int = 150,
              db: Session = Depends(get_db)):
    return news.listing(db, currency, topic, tone, kind, q, max(1, min(days, 30)), max(10, min(limit, 500)))


@router.post("/refresh")
def news_refresh(db: Session = Depends(get_db)):
    """Fetch the feeds now (same as Run now on Data health)."""
    from app.ingestion.registry import run

    return run(db, "news")
