from __future__ import annotations

import secrets
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lead, OutreachEvent, Suppression
from app.settings import get_settings

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class OutreachWebhookEvent(BaseModel):
    event_type: str  # replied|bounced|opt_out
    lead_id: UUID | None = None
    email_or_domain: str | None = None
    payload: dict[str, object] | None = None


class OutreachWebhookRequest(BaseModel):
    events: list[OutreachWebhookEvent]


def _require_webhook_secret(token: str | None) -> None:
    settings = get_settings()
    if not settings.webhook_shared_secret:
        raise HTTPException(status_code=503, detail="webhook_secret_not_configured")
    if not token or not secrets.compare_digest(token, settings.webhook_shared_secret):
        raise HTTPException(status_code=401, detail="invalid_webhook_token")


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).netloc.lower() or None


def _find_lead_by_email_or_domain(db: Session, value: str) -> Lead | None:
    normalized = value.lower().strip()
    lead = db.execute(select(Lead).where(Lead.email == normalized)).scalar_one_or_none()
    if lead is not None:
        return lead
    for candidate in db.execute(select(Lead).where(Lead.website_url.is_not(None))).scalars():
        if _domain_from_url(candidate.website_url) == normalized:
            return candidate
    return None


def _upsert_suppression(db: Session, *, value: str, reason: str) -> None:
    row = db.execute(select(Suppression).where(Suppression.email_or_domain == value)).scalar_one_or_none()
    if row is None:
        db.add(Suppression(email_or_domain=value, reason=reason))


@router.post("/outreach-events")
def ingest_outreach_events(
    body: OutreachWebhookRequest,
    x_webhook_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _require_webhook_secret(x_webhook_token)

    processed = 0
    rejected: list[dict[str, object]] = []
    allowed = {"replied", "bounced", "opt_out"}

    for item in body.events:
        event_type = item.event_type.strip().lower()
        if event_type not in allowed:
            rejected.append({"reason": "invalid_event_type", "event_type": item.event_type})
            continue

        lead = db.get(Lead, item.lead_id) if item.lead_id else None
        if lead is None and item.email_or_domain:
            lead = _find_lead_by_email_or_domain(db, item.email_or_domain)
        if lead is None:
            rejected.append(
                {
                    "reason": "lead_not_found",
                    "lead_id": str(item.lead_id) if item.lead_id else None,
                    "email_or_domain": item.email_or_domain,
                }
            )
            continue

        suppression_value = (item.email_or_domain or lead.email or _domain_from_url(lead.website_url) or "").lower()
        if event_type in {"bounced", "opt_out"} and suppression_value:
            _upsert_suppression(db, value=suppression_value, reason=event_type)
            lead.status = "Suppressed"
        elif event_type == "replied":
            lead.status = "Replied"

        db.add(
            OutreachEvent(
                lead_id=lead.id,
                type=event_type,
                payload={
                    "source": "webhook",
                    "email_or_domain": suppression_value or None,
                    "payload": item.payload,
                },
            )
        )
        processed += 1

    db.commit()
    return {"status": "ok", "processed": processed, "rejected": rejected}

