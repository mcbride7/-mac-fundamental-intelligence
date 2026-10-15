import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="mfi-test-")
# Tests NEVER use the real database: DATABASE_URL is replaced by TEST_DATABASE_URL
# (set it to test on PostgreSQL) or a throwaway SQLite file.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db"
os.environ["STORAGE_DIR"] = f"{_tmp}/storage"
os.environ["RECOMPUTE_INLINE"] = "1"
os.environ["LLM_PROVIDER"] = "none"
os.environ.pop("API_TOKEN", None)


@pytest.fixture()
def db():
    from app.db import Base, SessionLocal, engine, init_db
    from app.seed import seed

    Base.metadata.drop_all(engine)
    init_db()
    s = SessionLocal()
    seed(s)
    yield s
    s.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c
