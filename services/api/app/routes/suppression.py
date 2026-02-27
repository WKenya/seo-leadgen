from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Suppression
from app.schemas import SuppressionRead

router = APIRouter(prefix="/suppression", tags=["suppression"])


@router.get("")
def list_suppression(
    q: str | None = Query(default=None, description="substring filter"),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=5000),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    base = select(Suppression)
    if q:
        base = base.where(Suppression.email_or_domain.ilike(f"%{q}%"))
    total = int(db.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    stmt = base.order_by(Suppression.created_at.desc()).offset(offset).limit(limit)
    rows = db.execute(stmt).scalars().all()
    items = [SuppressionRead.from_model(row).model_dump() for row in rows]
    count = len(items)
    return {"items": items, "count": count, "total": total, "has_more": (offset + count) < total, "limit": limit, "offset": offset}
