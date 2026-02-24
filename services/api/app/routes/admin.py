from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EmailDraft, Lead, OutreachEvent, Suppression
from app.queue import celery_client
from app.settings import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])


class OptOutRequest(BaseModel):
    reason: str = "manual"
    email_or_domain: str | None = None


def _lead_suppression_key(lead: Lead) -> str | None:
    if lead.email:
        return lead.email.lower()
    if lead.website_url:
        return urlparse(lead.website_url).netloc.lower() or None
    return None


def _is_suppressed(db: Session, lead: Lead) -> bool:
    keys: list[str] = []
    if lead.email:
        keys.append(lead.email.lower())
    domain = urlparse(lead.website_url).netloc.lower() if lead.website_url else None
    if domain:
        keys.append(domain)
    if not keys:
        return False
    return db.execute(select(Suppression).where(Suppression.email_or_domain.in_(keys))).scalar_one_or_none() is not None


def _sent_count_today(db: Session) -> int:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    stmt = select(func.count()).select_from(EmailDraft).where(EmailDraft.sent_at >= start, EmailDraft.sent_at < end)
    return int(db.execute(stmt).scalar_one())


@router.post("/run-discovery")
def run_discovery(
    city: str = "Cleveland, OH",
    category: str = "HVAC",
    radius_meters: int = 15000,
) -> dict[str, str]:
    task = celery_client.send_task(
        "discover_leads",
        kwargs={"city": city, "category": category, "radius_meters": radius_meters},
    )
    return {"status": "queued", "task_id": task.id}


@router.post("/run-audit/{lead_id}")
def run_audit(lead_id: str) -> dict[str, str]:
    task = celery_client.send_task("audit_lead", kwargs={"lead_id": lead_id})
    return {"lead_id": lead_id, "status": "queued", "task_id": task.id}


@router.post("/run-summarize/{lead_id}/{audit_id}")
def run_summarize(lead_id: str, audit_id: str) -> dict[str, str]:
    task = celery_client.send_task("summarize_and_draft", kwargs={"lead_id": lead_id, "audit_id": audit_id})
    return {"lead_id": lead_id, "audit_id": audit_id, "status": "queued", "task_id": task.id}


@router.post("/run-notion-sync/{lead_id}")
def run_notion_sync(
    lead_id: str,
    audit_id: str | None = None,
    draft_id: str | None = None,
) -> dict[str, str]:
    task = celery_client.send_task("sync_notion", kwargs={"lead_id": lead_id, "audit_id": audit_id, "draft_id": draft_id})
    return {"lead_id": lead_id, "status": "queued", "task_id": task.id}


@router.post("/approve-draft/{draft_id}")
def approve_draft(draft_id: UUID, db: Session = Depends(get_db)) -> dict[str, str]:
    draft = db.get(EmailDraft, draft_id)
    if draft is None:
        return {"draft_id": str(draft_id), "status": "not_found"}
    lead = db.get(Lead, draft.lead_id)
    if lead is None:
        return {"draft_id": str(draft_id), "status": "lead_not_found"}

    if _is_suppressed(db, lead):
        lead.status = "Suppressed"
        db.add(OutreachEvent(lead_id=lead.id, type="approved_blocked_suppressed", payload={"draft_id": str(draft.id)}))
        db.commit()
        return {"draft_id": str(draft_id), "status": "suppressed"}

    if draft.approved_at is None:
        draft.approved_at = datetime.now(timezone.utc)
    lead.status = "Approved to Send"
    db.add(OutreachEvent(lead_id=lead.id, type="approved", payload={"draft_id": str(draft.id)}))
    db.commit()
    return {"draft_id": str(draft_id), "status": "approved"}


@router.post("/send-draft/{draft_id}")
def send_draft(draft_id: UUID, db: Session = Depends(get_db)) -> dict[str, str]:
    settings = get_settings()
    draft = db.get(EmailDraft, draft_id)
    if draft is None:
        return {"draft_id": str(draft_id), "status": "not_found"}
    lead = db.get(Lead, draft.lead_id)
    if lead is None:
        return {"draft_id": str(draft_id), "status": "lead_not_found"}

    if _is_suppressed(db, lead):
        lead.status = "Suppressed"
        db.add(OutreachEvent(lead_id=lead.id, type="send_blocked_suppressed", payload={"draft_id": str(draft.id)}))
        db.commit()
        return {"draft_id": str(draft_id), "status": "suppressed"}

    if draft.approved_at is None:
        return {"draft_id": str(draft_id), "status": "not_approved"}

    sent_today = _sent_count_today(db)
    if sent_today >= settings.daily_send_cap:
        db.add(
            OutreachEvent(
                lead_id=lead.id,
                type="send_blocked_cap",
                payload={"draft_id": str(draft.id), "daily_send_cap": settings.daily_send_cap, "sent_today": sent_today},
            )
        )
        db.commit()
        return {"draft_id": str(draft_id), "status": "daily_cap_reached"}

    now = datetime.now(timezone.utc)
    draft.sent_at = now
    lead.status = "Sent"
    db.add(
        OutreachEvent(
            lead_id=lead.id,
            type="sent",
            payload={"draft_id": str(draft.id), "mode": "manual_stub", "sent_at": now.isoformat()},
        )
    )
    db.commit()
    return {"draft_id": str(draft_id), "status": "sent_stubbed"}


@router.post("/mark-optout/{lead_id}")
def mark_optout(
    lead_id: UUID,
    payload: OptOutRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        return {"lead_id": str(lead_id), "status": "not_found"}

    value = payload.email_or_domain
    if not value:
        value = _lead_suppression_key(lead)
    if not value:
        return {"lead_id": str(lead_id), "status": "missing_suppression_target"}

    suppression = db.execute(select(Suppression).where(Suppression.email_or_domain == value)).scalar_one_or_none()
    if suppression is None:
        db.add(Suppression(email_or_domain=value, reason=payload.reason))
    lead.status = "Suppressed"
    db.add(OutreachEvent(lead_id=lead.id, type="opt_out", payload={"reason": payload.reason, "value": value}))
    db.commit()
    return {"lead_id": str(lead_id), "status": "suppressed"}
