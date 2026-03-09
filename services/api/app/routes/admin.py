from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
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


class RecordEventRequest(BaseModel):
    event_type: str = Field(description="replied|bounced|opt_out|manual")
    note: str | None = None
    email_or_domain: str | None = None
    suppress: bool | None = None


class UnsuppressRequest(BaseModel):
    email_or_domain: str | None = None


class DiscoveryBatchRequest(BaseModel):
    city: str = "Cleveland, OH"
    categories: list[str]
    radius_meters: int = 15000
    limit: int | None = None


class AuditBatchRequest(BaseModel):
    statuses: list[str] = ["Discovered"]
    limit: int = 25


def _lead_suppression_key(lead: Lead) -> str | None:
    if lead.email:
        return lead.email.strip().lower()
    if lead.website_domain:
        return lead.website_domain.strip().lower()
    if lead.website_url:
        domain = urlparse(lead.website_url.strip()).netloc.strip().lower()
        return domain or None
    return None


def _normalize_suppression_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _is_suppressed(db: Session, lead: Lead) -> bool:
    keys: list[str] = []
    if lead.email:
        normalized_email = _normalize_suppression_value(lead.email)
        if normalized_email:
            keys.append(normalized_email)
    domain = _normalize_suppression_value(lead.website_domain) or (
        _normalize_suppression_value(urlparse(lead.website_url.strip()).netloc) if lead.website_url else None
    )
    if domain:
        keys.append(domain)
    if not keys:
        return False
    return (
        db.execute(
            select(Suppression).where(func.lower(func.trim(func.coalesce(Suppression.email_or_domain, ""))).in_(keys))
        ).scalar_one_or_none()
        is not None
    )


def _sent_count_today(db: Session) -> int:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    stmt = select(func.count()).select_from(EmailDraft).where(EmailDraft.sent_at >= start, EmailDraft.sent_at < end)
    return int(db.execute(stmt).scalar_one())


def _upsert_suppression(db: Session, *, value: str, reason: str) -> None:
    normalized_value = _normalize_suppression_value(value)
    if not normalized_value:
        return
    suppression = db.execute(
        select(Suppression).where(
            func.lower(func.trim(func.coalesce(Suppression.email_or_domain, ""))) == normalized_value
        )
    ).scalar_one_or_none()
    if suppression is None:
        db.add(Suppression(email_or_domain=normalized_value, reason=reason))


@router.post("/run-discovery")
def run_discovery(
    city: str = "Cleveland, OH",
    category: str = "HVAC",
    radius_meters: int = 15000,
    limit: int | None = None,
) -> dict[str, str]:
    task = celery_client.send_task(
        "discover_leads",
        kwargs={"city": city, "category": category, "radius_meters": radius_meters, "limit": limit},
    )
    return {"status": "queued", "task_id": task.id}


@router.post("/run-discovery-batch")
def run_discovery_batch(payload: DiscoveryBatchRequest) -> dict[str, object]:
    items: list[dict[str, str]] = []
    for raw_category in payload.categories:
        category = raw_category.strip()
        if not category:
            continue
        task = celery_client.send_task(
            "discover_leads",
            kwargs={
                "city": payload.city,
                "category": category,
                "radius_meters": payload.radius_meters,
                "limit": payload.limit,
            },
        )
        items.append({"category": category, "task_id": task.id})
    return {"status": "queued", "count": len(items), "items": items}


@router.post("/run-audit/{lead_id}")
def run_audit(lead_id: str) -> dict[str, str]:
    task = celery_client.send_task("audit_lead", kwargs={"lead_id": lead_id})
    return {"lead_id": lead_id, "status": "queued", "task_id": task.id}


@router.post("/run-audit-batch")
def run_audit_batch(payload: AuditBatchRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    statuses = [s.strip().lower() for s in payload.statuses if s.strip()]
    limit = max(1, min(int(payload.limit), 200))
    stmt = select(Lead).order_by(Lead.created_at.desc()).limit(limit)
    if statuses:
        stmt = stmt.where(func.lower(func.trim(func.coalesce(Lead.status, ""))).in_(statuses))
    leads = db.execute(stmt).scalars().all()

    items: list[dict[str, str]] = []
    for lead in leads:
        task = celery_client.send_task("audit_lead", kwargs={"lead_id": str(lead.id)})
        items.append({"lead_id": str(lead.id), "name": lead.name, "task_id": task.id})
    return {"status": "queued", "count": len(items), "items": items}


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


@router.post("/create-gmail-draft/{draft_id}")
def queue_gmail_draft(draft_id: str) -> dict[str, str]:
    task = celery_client.send_task("create_gmail_draft", kwargs={"draft_id": draft_id})
    return {"draft_id": draft_id, "status": "queued", "task_id": task.id}


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


@router.post("/record-event/{lead_id}")
def record_event(
    lead_id: UUID,
    payload: RecordEventRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        return {"lead_id": str(lead_id), "status": "not_found"}

    event_type = payload.event_type.strip().lower()
    if event_type not in {"replied", "bounced", "opt_out", "manual"}:
        return {"lead_id": str(lead_id), "status": "invalid_event_type"}

    suppression_target = _normalize_suppression_value(payload.email_or_domain) or _lead_suppression_key(lead)
    should_suppress = payload.suppress
    if should_suppress is None:
        should_suppress = event_type in {"bounced", "opt_out"}

    if should_suppress and suppression_target:
        _upsert_suppression(db, value=suppression_target, reason=event_type)
        lead.status = "Suppressed"
    elif event_type == "replied":
        lead.status = "Replied"

    db.add(
        OutreachEvent(
            lead_id=lead.id,
            type=event_type,
            payload={
                "note": payload.note,
                "email_or_domain": suppression_target if should_suppress else None,
                "suppressed": bool(should_suppress and suppression_target),
            },
        )
    )
    db.commit()
    return {"lead_id": str(lead_id), "status": "recorded", "event_type": event_type}


@router.post("/unsuppress/{lead_id}")
def unsuppress_lead(
    lead_id: UUID,
    payload: UnsuppressRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        return {"lead_id": str(lead_id), "status": "not_found"}

    value = _normalize_suppression_value(payload.email_or_domain) or _lead_suppression_key(lead)
    if not value:
        return {"lead_id": str(lead_id), "status": "missing_suppression_target"}

    suppression = db.execute(
        select(Suppression).where(func.lower(func.trim(func.coalesce(Suppression.email_or_domain, ""))) == value)
    ).scalar_one_or_none()
    if suppression is None:
        return {"lead_id": str(lead_id), "status": "not_suppressed"}

    db.delete(suppression)
    if (lead.status or "").strip().lower() == "suppressed":
        lead.status = "Discovered"
    db.add(OutreachEvent(lead_id=lead.id, type="unsuppress", payload={"value": value}))
    db.commit()
    return {"lead_id": str(lead_id), "status": "unsuppressed"}


@router.post("/mark-optout/{lead_id}")
def mark_optout(
    lead_id: UUID,
    payload: OptOutRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    lead = db.get(Lead, lead_id)
    if lead is None:
        return {"lead_id": str(lead_id), "status": "not_found"}

    value = _normalize_suppression_value(payload.email_or_domain) or _lead_suppression_key(lead)
    if not value:
        return {"lead_id": str(lead_id), "status": "missing_suppression_target"}

    _upsert_suppression(db, value=value, reason=payload.reason)
    lead.status = "Suppressed"
    db.add(OutreachEvent(lead_id=lead.id, type="opt_out", payload={"reason": payload.reason, "value": value}))
    db.commit()
    return {"lead_id": str(lead_id), "status": "suppressed"}
