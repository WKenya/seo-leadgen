from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "service": "seo-lead-api"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> dict[str, object]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"db_unready: {exc}") from exc
    return {"ok": True, "db": "ready"}
