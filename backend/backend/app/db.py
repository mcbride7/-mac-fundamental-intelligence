"""Database engine, session and initialisation (PostgreSQL + TimescaleDB)."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or settings.database_url
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    return create_engine(url, **kwargs)


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Time-series tables converted to TimescaleDB hypertables: (table, time column)
HYPERTABLES = [
    ("market_prices", "ts"),
    ("bond_yields", "ts"),
    ("rate_expectations", "ts"),
]


def init_db(bind=None) -> None:
    """Create all tables and, on PostgreSQL with TimescaleDB, the hypertables."""
    from app import models  # noqa: F401  (register models)

    bind = bind or engine
    if bind.dialect.name == "postgresql" and settings.use_timescale:
        try:
            with bind.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
        except Exception as exc:  # extension not installed: plain Postgres still works
            log.warning("TimescaleDB extension unavailable, continuing without it: %s", exc)
    Base.metadata.create_all(bind)
    if bind.dialect.name == "postgresql" and settings.use_timescale:
        for table, col in HYPERTABLES:
            try:
                with bind.begin() as conn:
                    conn.execute(
                        text(
                            "SELECT create_hypertable(:t, :c, if_not_exists => TRUE, migrate_data => TRUE)"
                        ),
                        {"t": table, "c": col},
                    )
            except Exception as exc:
                log.warning("Could not create hypertable %s: %s", table, exc)
