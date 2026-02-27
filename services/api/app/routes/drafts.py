from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EmailDraft, Lead, OutreachEvent
from app.schemas import EmailDraftRead, OutreachEventRead

router = APIRouter(tags=["drafts"])


@router.get("/events")
def list_events(
    event_type: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=5000),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    stmt = select(OutreachEvent).order_by(OutreachEvent.created_at.desc())
    if event_type:
        stmt = stmt.where(OutreachEvent.type == event_type)
    events = db.execute(stmt).scalars().all()
    if provider:
        provider_value = provider.strip().lower()
        events = [event for event in events if str((event.payload or {}).get("provider") or "").lower() == provider_value]
    events = events[offset : offset + limit]
    return {"items": [OutreachEventRead.from_model(event).model_dump() for event in events], "limit": limit, "offset": offset}


@router.get("/drafts")
def list_drafts(
    lead_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=5000),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    stmt = select(EmailDraft).order_by(EmailDraft.created_at.desc()).offset(offset).limit(limit)
    if lead_id is not None:
        stmt = stmt.where(EmailDraft.lead_id == lead_id)
    drafts = db.execute(stmt).scalars().all()
    return {"items": [EmailDraftRead.from_model(draft).model_dump() for draft in drafts], "limit": limit, "offset": offset}


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    draft = db.get(EmailDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="draft not found")
    return EmailDraftRead.from_model(draft).model_dump()


@router.get("/leads/{lead_id}/drafts")
def list_lead_drafts(
    lead_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=5000),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    drafts = (
        db.execute(
            select(EmailDraft)
            .where(EmailDraft.lead_id == lead_id)
            .order_by(EmailDraft.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {"items": [EmailDraftRead.from_model(draft).model_dump() for draft in drafts], "limit": limit, "offset": offset}


@router.get("/leads/{lead_id}/events")
def list_lead_events(
    lead_id: UUID,
    event_type: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=5000),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    stmt = select(OutreachEvent).where(OutreachEvent.lead_id == lead_id).order_by(OutreachEvent.created_at.desc())
    if event_type:
        stmt = stmt.where(OutreachEvent.type == event_type)
    events = db.execute(stmt).scalars().all()
    if provider:
        provider_value = provider.strip().lower()
        events = [event for event in events if str((event.payload or {}).get("provider") or "").lower() == provider_value]
    events = events[offset : offset + limit]
    return {"items": [OutreachEventRead.from_model(event).model_dump() for event in events], "limit": limit, "offset": offset}
