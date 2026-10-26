"""COT positioning (CFTC Commitments of Traders, Legacy futures-only)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import Auth, current_user_id, get_db
from app.services import cot
from app.services.audit import audit

router = APIRouter(prefix="/api/cot", tags=["cot"], dependencies=[Auth])


@router.get("")
def cot_board(db: Session = Depends(get_db)):
    """Latest week for every market: speculator and commercial net, weekly change, COT index, signals."""
    cot.import_bundled(db)
    return {"markets": cot.board(db), "groups": cot.GROUP_ORDER}


@router.get("/{code}")
def cot_market(code: str, weeks: int | None = None, db: Session = Depends(get_db)):
    try:
        return cot.market(db, code.upper(), weeks)
    except LookupError as exc:
        raise HTTPException(404, str(exc))


class PriceIn(BaseModel):
    price: float | None = None


@router.put("/{code}/weeks/{day}/price")
def cot_set_price(code: str, day: date, body: PriceIn, db: Session = Depends(get_db),
                  user_id: int = Depends(current_user_id)):
    try:
        w = cot.set_price(db, code.upper(), day, body.price)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    audit(db, "cot_week", w.id, "price edited", user_id, price=body.price)
    db.commit()
    return {"code": w.code, "report_date": w.report_date, "price": w.price, "price_source": w.price_source}


class PasteIn(BaseModel):
    text: str


@router.post("/{code}/prices")
def cot_paste_prices(code: str, body: PasteIn, db: Session = Depends(get_db)):
    if code.upper() not in cot.MARKETS:
        raise HTTPException(404, "Unknown market")
    return cot.paste_prices(db, code.upper(), body.text)


class WeekIn(BaseModel):
    d: date
    oi: int | None = None
    ncl: int | None = None
    ncs: int | None = None
    cl: int | None = None
    cs: int | None = None
    nrl: int | None = None
    nrs: int | None = None
    price: float | None = None


@router.post("/{code}/weeks")
def cot_save_week(code: str, body: WeekIn, db: Session = Depends(get_db), user_id: int = Depends(current_user_id)):
    rec = body.model_dump(exclude_unset=True) | {"d": body.d.isoformat()}
    try:
        w = cot.save_week(db, code.upper(), rec)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    audit(db, "cot_week", w.id, "saved by hand", user_id)
    db.commit()
    return {"code": w.code, "report_date": w.report_date}


@router.post("/import")
async def cot_import(file: UploadFile = File(...), db: Session = Depends(get_db),
                     user_id: int = Depends(current_user_id)):
    """Merge a CFTC Legacy futures-only history file (deacot<YEAR>.zip or its .txt) or a CSV/JSON export."""
    data = await file.read()
    try:
        recs = cot.read_file(file.filename or "", data)
    except Exception as exc:
        raise HTTPException(400, f"Couldn't read that file ({exc.__class__.__name__}). Use the CFTC Legacy "
                                 "futures-only history file, or a CSV or JSON export.")
    if not recs:
        raise HTTPException(400, "No rows for the tracked markets were found in that file.")
    added, updated = cot.upsert(db, recs, "file")
    priced = cot.fill_prices(db)
    audit(db, "cot", None, "file imported", user_id, file=file.filename, added=added, updated=updated)
    db.commit()
    return {"rows_read": len(recs), "added": added, "updated": updated, "prices_filled": priced}
