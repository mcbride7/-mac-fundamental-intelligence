"""Top setups: every asset scored on central bank, economic data, COT, seasonality and retail sentiment."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import Auth, get_db
from app.services import retail
from app.services import setups as sv

router = APIRouter(prefix="/api/setups", tags=["setups"], dependencies=[Auth])


@router.get("")
def top_setups(limit: int | None = None, db: Session = Depends(get_db)):
    res = sv.compute(db)
    if limit:
        res = res | {"setups": res["setups"][:limit]}
    return res


@router.get("/table")
def setups_table(db: Session = Depends(get_db)):
    """Home-page Top setups table: every symbol scored -2..+2 per factor, summed."""
    from app.services import setups_table as tb

    return tb.compute(db)


@router.get("/retail")
def retail_board(days: int = 30, db: Session = Depends(get_db)):
    """Retail sentiment for every pair and metal: latest long %, weekly change, daily history."""
    return retail.board(db, max(7, min(days, 180)))


class RetailIn(BaseModel):
    long_pct: float


@router.put("/retail/{symbol}")
def set_retail(symbol: str, body: RetailIn, db: Session = Depends(get_db)):
    try:
        r = retail.set_manual(db, symbol, body.long_pct)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    sv.clear_cache()
    from app.services import setups_table as tb

    tb.clear_cache()
    return {"symbol": r.symbol, "long_pct": r.long_pct, "source": r.source, "as_of": r.as_of}
