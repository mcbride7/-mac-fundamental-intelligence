"""Recompute dependency graph (Section 66.8).

Each analysis node registers a handler and the nodes it depends on. When data
changes, the trigger maps to its entry nodes, and every downstream node runs
once, in topological order. Handlers return human-readable changes, which are
collected into the job summary shown to the user:

    "Re-analysis complete. USD score 72 → 79. Fed policy score 68 → 74. 2 alerts generated."
"""
from __future__ import annotations

import logging
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Alert, AnalysisDependency, RecomputeJob

log = logging.getLogger(__name__)


@dataclass
class Context:
    trigger_entity: str
    trigger_id: int | None
    central_banks: set[str] = field(default_factory=set)  # affected CB codes
    currencies: set[str] = field(default_factory=set)
    indicator_ids: set[int] = field(default_factory=set)
    release_ids: set[int] = field(default_factory=set)
    changes: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def change(self, text: str) -> None:
        if text and text not in self.changes:
            self.changes.append(text)


Handler = Callable[[Session, Context], None]


@dataclass
class Node:
    name: str
    handler: Handler
    depends_on: tuple[str, ...]
    label: str


_NODES: dict[str, Node] = {}

# trigger entity -> entry nodes
TRIGGERS: dict[str, list[str]] = defaultdict(list)


def node(name: str, depends_on: tuple[str, ...] = (), label: str | None = None,
         triggers: tuple[str, ...] = ()):
    """Decorator to register an analysis node."""

    def deco(fn: Handler) -> Handler:
        _NODES[name] = Node(name, fn, depends_on, label or name.replace("_", " "))
        for t in triggers:
            if name not in TRIGGERS[t]:
                TRIGGERS[t].append(name)
        return fn

    return deco


def downstream(start: list[str]) -> list[str]:
    """All nodes reachable from `start`, in a valid topological order."""
    children: dict[str, list[str]] = defaultdict(list)
    for n in _NODES.values():
        for d in n.depends_on:
            children[d].append(n.name)
    reach: set[str] = set()
    stack = [s for s in start if s in _NODES]
    while stack:
        cur = stack.pop()
        if cur in reach:
            continue
        reach.add(cur)
        stack.extend(children.get(cur, []))
    order: list[str] = []
    visited: set[str] = set()

    def visit(n: str) -> None:
        if n in visited:
            return
        visited.add(n)
        for d in _NODES[n].depends_on:
            if d in reach:
                visit(d)
        order.append(n)

    for n in sorted(reach):
        visit(n)
    return order


def graph() -> list[dict]:
    return [{"node": n.name, "label": n.label, "depends_on": list(n.depends_on)} for n in _NODES.values()]


def persist_graph(db: Session) -> None:
    db.query(AnalysisDependency).delete()
    for n in _NODES.values():
        for d in n.depends_on or ("<trigger>",):
            db.add(AnalysisDependency(node=n.name, depends_on=d))
    db.commit()


def _load_engines() -> None:
    # Import engines so their nodes register. Imported lazily to avoid cycles.
    from app.engines import (  # noqa: F401
        cb_engine,
        currency_engine,
        forecast_engine,
        market_engine,
        release_engine,
        research_engine,
        scenario_engine,
        trading_engine,
    )


def create_job(db: Session, entity: str, entity_id: int | None, ctx_extra: dict | None = None) -> RecomputeJob:
    _load_engines()
    nodes = downstream(TRIGGERS.get(entity, []))
    job = RecomputeJob(trigger_entity=entity, trigger_id=entity_id, status="queued", nodes=nodes,
                       summary={"ctx": ctx_extra or {}})
    db.add(job)
    db.commit()
    return job


def run_job(db: Session, job_id: int) -> RecomputeJob:
    _load_engines()
    job = db.get(RecomputeJob, job_id)
    extra = (job.summary or {}).get("ctx", {})
    ctx = Context(job.trigger_entity, job.trigger_id,
                  central_banks=set(extra.get("central_banks", [])),
                  currencies=set(extra.get("currencies", [])),
                  indicator_ids=set(extra.get("indicator_ids", [])),
                  release_ids=set(extra.get("release_ids", [])))
    if job.trigger_entity == "full":
        from app.models import CentralBank, Indicator

        ctx.indicator_ids = {i for (i,) in db.execute(select(Indicator.id))}
        ctx.central_banks = {c for (c,) in db.execute(select(CentralBank.code))}
        ctx.currencies = {c for (c,) in db.execute(select(CentralBank.currency))}
    alerts_before = db.scalar(select(func.count(Alert.id))) or 0
    job.status = "running"
    db.commit()
    done: list[str] = []
    failed: list[dict] = []
    for i, name in enumerate(job.nodes):
        n = _NODES.get(name)
        if n is None:
            continue
        try:
            n.handler(db, ctx)
            db.commit()
            done.append(name)
        except Exception as exc:  # one failing node must not block the rest
            db.rollback()
            log.exception("recompute node %s failed", name)
            failed.append({"node": name, "error": f"{exc.__class__.__name__}: {exc}",
                           "trace": traceback.format_exc(limit=3)})
        job = db.get(RecomputeJob, job_id)
        job.progress = int(100 * (i + 1) / max(1, len(job.nodes)))
        db.commit()
    alerts_after = db.scalar(select(func.count(Alert.id))) or 0
    n_alerts = alerts_after - alerts_before
    msg_parts = ["Re-analysis complete."] + ctx.changes
    if n_alerts:
        msg_parts.append(f"{n_alerts} alert{'s' if n_alerts != 1 else ''} generated.")
    job = db.get(RecomputeJob, job_id)
    job.status = "done" if not failed else ("failed" if not done else "done")
    job.progress = 100
    job.summary = {"message": " ".join(msg_parts), "changes": ctx.changes, "alerts": n_alerts,
                   "nodes_run": done, "failed": failed, "metrics": ctx.metrics}
    job.finished_at = utcnow()
    if failed and not done:
        job.error = failed[0]["error"]
    db.commit()
    return job


def trigger(db: Session, entity: str, entity_id: int | None = None, **ctx_extra) -> RecomputeJob:
    """Create a job and run it inline, or hand it to Celery."""
    from app.config import settings

    ctx_extra = {k: sorted(v) if isinstance(v, set) else v for k, v in ctx_extra.items()}
    job = create_job(db, entity, entity_id, ctx_extra)
    if settings.recompute_inline:
        return run_job(db, job.id)
    try:
        from app.worker import recompute_task

        recompute_task.delay(job.id)
    except Exception:  # broker unavailable -> run inline so analysis never stalls
        log.warning("Celery unavailable; running recompute inline")
        return run_job(db, job.id)
    return job
