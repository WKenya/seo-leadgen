from __future__ import annotations

import secrets
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lead, OutreachEvent, Suppression
from app.settings import get_settings
from app.webhook_auth import verify_hmac_request

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class OutreachWebhookEvent(BaseModel):
    event_id: str | None = None
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


def _verify_webhook_hmac(body: bytes, signature: str | None, timestamp_header: str | None) -> None:
    settings = get_settings()
    secret = settings.webhook_signature_secret
    if not secret:
        return
    try:
        verify_hmac_request(
            secret=secret,
            body=body,
            signature=signature,
            timestamp_header=timestamp_header,
            tolerance_seconds=settings.webhook_signature_tolerance_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


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
async def ingest_outreach_events(
    request: Request,
    x_webhook_token: str | None = Header(default=None),
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_timestamp: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    raw_body = await request.body()
    settings = get_settings()
    if settings.webhook_signature_secret:
        _verify_webhook_hmac(raw_body, x_webhook_signature, x_webhook_timestamp)
    else:
        _require_webhook_secret(x_webhook_token)
    try:
        body = OutreachWebhookRequest.model_validate_json(raw_body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid_body: {exc}") from exc

    processed = 0
    duplicates = 0
    rejected: list[dict[str, object]] = []
    allowed = {"replied", "bounced", "opt_out"}

    for item in body.events:
        event_type = item.event_type.strip().lower()
        if event_type not in allowed:
            rejected.append({"reason": "invalid_event_type", "event_type": item.event_type})
            continue
        external_id = item.event_id.strip() if item.event_id else None
        if external_id:
            exists = db.execute(select(OutreachEvent).where(OutreachEvent.external_id == external_id)).scalar_one_or_none()
            if exists is not None:
                duplicates += 1
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
                external_id=external_id,
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
    return {"status": "ok", "processed": processed, "duplicates": duplicates, "rejected": rejected}
