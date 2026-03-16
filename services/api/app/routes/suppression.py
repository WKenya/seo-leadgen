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
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    q_filter = (q or "").strip() or None
    normalized_value = func.lower(func.trim(func.coalesce(Suppression.email_or_domain, "")))
    base = select(Suppression).where(normalized_value != "")
    count_stmt = select(func.count()).select_from(Suppression).where(normalized_value != "")
    if q_filter:
        query_match = normalized_value.like(f"%{q_filter.lower()}%")
        base = base.where(query_match)
        count_stmt = count_stmt.where(query_match)
    total = int(db.execute(count_stmt).scalar_one())
    order_column = Suppression.created_at.asc() if sort == "asc" else Suppression.created_at.desc()
    stmt = base.order_by(order_column).offset(offset).limit(limit)
    rows = db.execute(stmt).scalars().all()
    items = [SuppressionRead.from_model(row).model_dump() for row in rows]
    count = len(items)
    return {
        "items": items,
        "count": count,
        "total": total,
        "has_more": (offset + count) < total,
        "next_offset": (offset + count) if (offset + count) < total else None,
        "sort": sort,
        "limit": limit,
        "offset": offset,
    }
