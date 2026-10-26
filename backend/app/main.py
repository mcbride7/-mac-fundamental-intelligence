"""FastAPI application entry point."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analysis, auth, central_banks, cot, data, economic, manual, markets, system
from app.config import settings
from app.db import SessionLocal, init_db
from app.seed import seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed(db)
        from app.services import recompute

        recompute._load_engines()
        recompute.persist_graph(db)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Fundamental macro trading intelligence: data → central-bank analysis → forecast accuracy → "
                "market impact → scenarios → trade bias (or NO TRADE). Decision support only.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

for r in (auth, system, manual, data, central_banks, economic, markets, analysis, cot):
    app.include_router(r.router)


@app.get("/health", tags=["system"])
def health():
    # version = the GitHub commit Railway deployed, so you can check an update went live
    return {"status": "ok", "app": settings.app_name,
            "version": (os.environ.get("RAILWAY_GIT_COMMIT_SHA") or "dev")[:7]}


@app.get("/health/deep", tags=["system"])
def health_deep():
    """For uptime monitors: 503 when the database is down or the worker has gone quiet."""
    from fastapi.responses import JSONResponse

    from app.services.ops import deep_health

    try:
        with SessionLocal() as db:
            ok, body = deep_health(db)
    except Exception as exc:
        ok, body = False, {"database": f"down ({exc.__class__.__name__})"}
    body["app"] = settings.app_name
    return JSONResponse(body, status_code=200 if ok else 503)
