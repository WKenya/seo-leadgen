from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lead, Suppression
from app.queue import celery_client

router = APIRouter(prefix="/admin", tags=["admin"])


class OptOutRequest(BaseModel):
    reason: str = "manual"
    email_or_domain: str | None = None


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
        value = lead.email
    if not value and lead.website_url:
        value = urlparse(lead.website_url).netloc.lower() or None
    if not value:
        return {"lead_id": str(lead_id), "status": "missing_suppression_target"}

    suppression = db.execute(select(Suppression).where(Suppression.email_or_domain == value)).scalar_one_or_none()
    if suppression is None:
        db.add(Suppression(email_or_domain=value, reason=payload.reason))
    lead.status = "Suppressed"
    db.commit()
    return {"lead_id": str(lead_id), "status": "suppressed"}
