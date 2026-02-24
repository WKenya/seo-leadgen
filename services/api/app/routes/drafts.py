from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EmailDraft, Lead, OutreachEvent
from app.schemas import EmailDraftRead, OutreachEventRead

router = APIRouter(tags=["drafts"])


@router.get("/events")
def list_events(db: Session = Depends(get_db)) -> dict[str, object]:
    events = db.execute(select(OutreachEvent).order_by(OutreachEvent.created_at.desc()).limit(200)).scalars().all()
    return {"items": [OutreachEventRead.from_model(event).model_dump() for event in events]}


@router.get("/drafts")
def list_drafts(
    lead_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    stmt = select(EmailDraft).order_by(EmailDraft.created_at.desc()).limit(100)
    if lead_id is not None:
        stmt = stmt.where(EmailDraft.lead_id == lead_id)
    drafts = db.execute(stmt).scalars().all()
    return {"items": [EmailDraftRead.from_model(draft).model_dump() for draft in drafts]}


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    draft = db.get(EmailDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    return EmailDraftRead.from_model(draft).model_dump()


@router.get("/leads/{lead_id}/drafts")
def list_lead_drafts(lead_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    drafts = (
        db.execute(select(EmailDraft).where(EmailDraft.lead_id == lead_id).order_by(EmailDraft.created_at.desc()))
        .scalars()
        .all()
    )
    return {"items": [EmailDraftRead.from_model(draft).model_dump() for draft in drafts]}


@router.get("/leads/{lead_id}/events")
def list_lead_events(lead_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    events = (
        db.execute(select(OutreachEvent).where(OutreachEvent.lead_id == lead_id).order_by(OutreachEvent.created_at.desc()))
        .scalars()
        .all()
    )
    return {"items": [OutreachEventRead.from_model(event).model_dump() for event in events]}
