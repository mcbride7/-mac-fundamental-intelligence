"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import analysis, central_banks, data, economic, manual, markets, system
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

for r in (system, manual, data, central_banks, economic, markets, analysis):
    app.include_router(r.router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "app": settings.app_name}
