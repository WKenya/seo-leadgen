from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EmailDraft, Lead, OutreachEvent
from app.schemas import EmailDraftRead, OutreachEventRead

router = APIRouter(tags=["drafts"])


def _apply_event_filters(
    base_stmt,  # type: ignore[no-untyped-def]
    *,
    event_type: str | None,
    provider: str | None,
):
    stmt = base_stmt
    event_type_value = (event_type or "").strip().lower()
    if event_type_value:
        stmt = stmt.where(func.lower(func.trim(func.coalesce(OutreachEvent.type, ""))) == event_type_value)
    provider_value = (provider or "").strip().lower()
    if provider_value:
        stmt = stmt.where(func.lower(func.trim(func.coalesce(OutreachEvent.provider, ""))) == provider_value)
    return stmt


@router.get("/events")
def list_events(
    event_type: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=5000),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    base = _apply_event_filters(select(OutreachEvent), event_type=event_type, provider=provider)
    total = int(db.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    order_column = OutreachEvent.created_at.asc() if sort == "asc" else OutreachEvent.created_at.desc()
    events = db.execute(base.order_by(order_column).offset(offset).limit(limit)).scalars().all()
    items = [OutreachEventRead.from_model(event).model_dump() for event in events]
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


@router.get("/drafts")
def list_drafts(
    lead_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=5000),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    base = select(EmailDraft)
    if lead_id is not None:
        base = base.where(EmailDraft.lead_id == lead_id)
    total = int(db.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    order_column = EmailDraft.created_at.asc() if sort == "asc" else EmailDraft.created_at.desc()
    drafts = db.execute(base.order_by(order_column).offset(offset).limit(limit)).scalars().all()
    items = [EmailDraftRead.from_model(draft).model_dump() for draft in drafts]
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
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    base = select(EmailDraft).where(EmailDraft.lead_id == lead_id)
    total = int(db.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    order_column = EmailDraft.created_at.asc() if sort == "asc" else EmailDraft.created_at.desc()
    drafts = db.execute(base.order_by(order_column).offset(offset).limit(limit)).scalars().all()
    items = [EmailDraftRead.from_model(draft).model_dump() for draft in drafts]
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


@router.get("/leads/{lead_id}/events")
def list_lead_events(
    lead_id: UUID,
    event_type: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=5000),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    base = _apply_event_filters(select(OutreachEvent).where(OutreachEvent.lead_id == lead_id), event_type=event_type, provider=provider)
    total = int(db.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    order_column = OutreachEvent.created_at.asc() if sort == "asc" else OutreachEvent.created_at.desc()
    events = db.execute(base.order_by(order_column).offset(offset).limit(limit)).scalars().all()
    items = [OutreachEventRead.from_model(event).model_dump() for event in events]
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
