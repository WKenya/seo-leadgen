from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Audit, EmailDraft, Lead, OutreachEvent
from app.schemas import AuditRead, EmailDraftRead, LeadRead, OutreachEventRead

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


@router.get("/{lead_id}/pipeline")
def get_lead_pipeline(lead_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")

    latest_audit = (
        db.execute(select(Audit).where(Audit.lead_id == lead_id).order_by(Audit.finished_at.desc(), Audit.started_at.desc()))
        .scalars()
        .first()
    )
    latest_draft = (
        db.execute(select(EmailDraft).where(EmailDraft.lead_id == lead_id).order_by(EmailDraft.created_at.desc()))
        .scalars()
        .first()
    )
    recent_events = (
        db.execute(select(OutreachEvent).where(OutreachEvent.lead_id == lead_id).order_by(OutreachEvent.created_at.desc()).limit(10))
        .scalars()
        .all()
    )

    return {
        "lead": LeadRead.from_model(lead).model_dump(),
        "latest_audit": AuditRead.from_model(latest_audit).model_dump() if latest_audit else None,
        "latest_draft": EmailDraftRead.from_model(latest_draft).model_dump() if latest_draft else None,
        "recent_events": [OutreachEventRead.from_model(event).model_dump() for event in recent_events],
    }
