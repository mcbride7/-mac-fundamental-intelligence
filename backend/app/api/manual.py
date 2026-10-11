"""Manual data ingestion API (Section 66.15)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Auth, current_user_id, get_db
from app.models import ManualSubmission
from app.services import manual_service as ms
from app.services.storage import UploadRejected

router = APIRouter(prefix="/api/manual", tags=["manual data"], dependencies=[Auth])


class TextIn(BaseModel):
    text: str
    hint: dict | None = None
    content_type: str | None = None
    input_method: str = "typed"


class UrlIn(BaseModel):
    url: str
    hint: dict | None = None
    content_type: str | None = None


class RowIn(BaseModel):
    id: int
    fields: dict | None = None
    override_reason: str | None = None
    include: bool = True


class ConfirmIn(BaseModel):
    rows: list[RowIn] | None = None
    confirm: dict | None = None  # {"basis": OFFICIAL_SOURCE|SECONDARY_SOURCE|NO_SOURCE, "source_name", ...}


class PointPatch(BaseModel):
    fields: dict


def _hint(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(422, "hint must be JSON")


@router.post("/upload")
async def upload(file: UploadFile = File(...), hint: str | None = Form(None), input_method: str | None = Form(None),
                 content_type: str | None = Form(None), db: Session = Depends(get_db),
                 user_id: int = Depends(current_user_id)):
    data = await file.read()
    try:
        sub = ms.submit_file(db, data, file.filename or "upload", file.content_type or "", user_id, _hint(hint),
                             input_method, content_type)
    except UploadRejected as exc:
        raise HTTPException(415, str(exc))
    return ms.serialize_submission(db, sub)


@router.post("/text")
def submit_text(body: TextIn, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    if not body.text.strip():
        raise HTTPException(422, "Empty text")
    sub = ms.submit_text(db, body.text, user_id, body.hint, body.input_method, body.content_type)
    return ms.serialize_submission(db, sub)


@router.post("/url")
def submit_url(body: UrlIn, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    sub = ms.submit_url(db, body.url, user_id, body.hint, body.content_type)
    return ms.serialize_submission(db, sub)


@router.get("")
def list_submissions(limit: int = 30, db: Session = Depends(get_db)):
    subs = db.scalars(select(ManualSubmission).order_by(ManualSubmission.created_at.desc()).limit(limit))
    return [{"id": s.id, "input_method": s.input_method, "content_type": s.content_type, "status": s.status,
             "created_at": s.created_at, "error": s.error} for s in subs]


@router.get("/{sub_id}/extraction")
def extraction(sub_id: int, db: Session = Depends(get_db)):
    sub = db.get(ManualSubmission, sub_id)
    if sub is None:
        raise HTTPException(404, "Submission not found")
    return ms.serialize_submission(db, sub)


@router.patch("/points/{point_id}")
def patch_point(point_id: int, body: PointPatch, db: Session = Depends(get_db),
                user_id: int = Depends(current_user_id)):
    try:
        p = ms.update_point(db, point_id, body.fields, user_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return ms.serialize_point(p)


@router.post("/{sub_id}/confirm")
def confirm(sub_id: int, body: ConfirmIn | None = None, db: Session = Depends(get_db),
            user_id: int = Depends(current_user_id)):
    body = body or ConfirmIn()
    try:
        return ms.commit(db, sub_id, user_id, [r.model_dump() for r in body.rows] if body.rows else None,
                         body.confirm)
    except ms.CommitBlocked as exc:
        raise HTTPException(422, {"message": str(exc), "problems": exc.problems})
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@router.post("/{sub_id}/discard")
def discard(sub_id: int, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    try:
        sub = ms.discard(db, sub_id, user_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    return {"id": sub.id, "status": sub.status}


@router.delete("/{sub_id}")
def delete_upload(sub_id: int, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    try:
        return ms.delete_upload(db, sub_id, user_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
