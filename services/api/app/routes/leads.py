from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Audit, EmailDraft, Lead, OutreachEvent
from app.schemas import AuditRead, EmailDraftRead, LeadRead, OutreachEventRead

router = APIRouter(prefix="/leads", tags=["leads"])


@router.get("")
def list_leads(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, description="name/domain substring"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=5000),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    status_filter = (status or "").strip() or None
    q_filter = (q or "").strip() or None
    base = select(Lead)
    if status_filter:
        base = base.where(Lead.status == status_filter)
    if q_filter:
        like = f"%{q_filter}%"
        base = base.where((Lead.name.ilike(like)) | (Lead.website_url.ilike(like)))
    total = int(db.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    order_column = Lead.created_at.asc() if sort == "asc" else Lead.created_at.desc()
    stmt = base.order_by(order_column).offset(offset).limit(limit)
    leads = db.execute(stmt).scalars().all()
    items = [LeadRead.from_model(lead).model_dump() for lead in leads]
    count = len(items)
    return {
        "items": items,
        "count": count,
        "total": total,
        "has_more": (offset + count) < total,
        "next_offset": (offset + count) if (offset + count) < total else None,
        "status_filter": status_filter,
        "q": q_filter,
        "sort": sort,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{lead_id}")
def get_lead(lead_id: UUID, db: Session = Depends(get_db)) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    return LeadRead.from_model(lead).model_dump()


@router.get("/{lead_id}/audits")
def list_lead_audits(
    lead_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=5000),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="lead not found")
    base = select(Audit).where(Audit.lead_id == lead_id)
    total = int(db.execute(select(func.count()).select_from(base.subquery())).scalar_one())
    order_column = Audit.started_at.asc() if sort == "asc" else Audit.started_at.desc()
    audits = db.execute(base.order_by(order_column).offset(offset).limit(limit)).scalars().all()
    items = [AuditRead.from_model(audit).model_dump() for audit in audits]
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
