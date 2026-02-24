from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Suppression
from app.schemas import SuppressionRead

router = APIRouter(prefix="/suppression", tags=["suppression"])


@router.get("")
def list_suppression(
    q: str | None = Query(default=None, description="substring filter"),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    stmt = select(Suppression).order_by(Suppression.created_at.desc()).limit(limit)
    if q:
        stmt = stmt.where(Suppression.email_or_domain.ilike(f"%{q}%"))
    rows = db.execute(stmt).scalars().all()
    return {"items": [SuppressionRead.from_model(row).model_dump() for row in rows], "limit": limit}
