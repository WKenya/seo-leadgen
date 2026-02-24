from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Audit, Lead
from app.schemas import AuditRead, LeadRead

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


@router.get("/{lead_id}/audits")
def list_lead_audits(lead_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    audits = (
        db.execute(select(Audit).where(Audit.lead_id == lead_id).order_by(Audit.started_at.desc()))
        .scalars()
        .all()
    )
    return {"items": [AuditRead.from_model(audit).model_dump() for audit in audits]}
