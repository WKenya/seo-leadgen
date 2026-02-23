from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lead
from app.schemas import LeadRead

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("")
def list_leads(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    stmt = select(Lead).order_by(Lead.created_at.desc()).limit(100)
    if status:
        stmt = stmt.where(Lead.status == status)
    leads = db.execute(stmt).scalars().all()
    return {"items": [LeadRead.from_model(lead).model_dump() for lead in leads], "status_filter": status}


@router.get("/{lead_id}")
def get_lead(lead_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    return LeadRead.from_model(lead).model_dump()
