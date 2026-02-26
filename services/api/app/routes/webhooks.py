from __future__ import annotations

import json
import secrets
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lead, OutreachEvent, Suppression
from app.settings import get_settings
from app.webhook_auth import verify_hmac_request, verify_mailgun_signature, verify_sendgrid_signature

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


def _require_postmark_token(token: str | None) -> None:
    settings = get_settings()
    if not settings.postmark_webhook_token:
        raise HTTPException(status_code=503, detail="postmark_webhook_token_not_configured")
    if not token or not secrets.compare_digest(token, settings.postmark_webhook_token):
        raise HTTPException(status_code=401, detail="invalid_postmark_webhook_token")


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


def _extract_mailgun_signature_fields(raw_body: bytes, *, content_type: str | None) -> tuple[str, str, str] | None:
    content_type_value = (content_type or "").split(";", 1)[0].strip().lower()
    if content_type_value == "application/x-www-form-urlencoded":
        parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
        ts = (parsed.get("signature[timestamp]") or [None])[0]
        token = (parsed.get("signature[token]") or [None])[0]
        sig = (parsed.get("signature[signature]") or [None])[0]
        if ts or token or sig:
            return (str(ts or ""), str(token or ""), str(sig or ""))
        return None

    try:
        raw = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, dict):
        return None
    signature = raw.get("signature")
    if not isinstance(signature, dict):
        return None
    ts = signature.get("timestamp")
    token = signature.get("token")
    sig = signature.get("signature")
    if ts is None and token is None and sig is None:
        return None
    return (str(ts or ""), str(token or ""), str(sig or ""))


def _verify_mailgun_webhook_signature(raw_body: bytes, *, content_type: str | None) -> bool:
    settings = get_settings()
    if not settings.mailgun_webhook_signing_key:
        return False
    fields = _extract_mailgun_signature_fields(raw_body, content_type=content_type)
    if fields is None:
        return False
    timestamp, token, signature = fields
    try:
        verify_mailgun_signature(
            signing_key=settings.mailgun_webhook_signing_key,
            timestamp=timestamp,
            token=token,
            signature=signature,
            tolerance_seconds=settings.mailgun_webhook_signature_tolerance_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return True


def _verify_sendgrid_webhook_signature(
    raw_body: bytes,
    *,
    signature_header: str | None,
    timestamp_header: str | None,
) -> bool:
    settings = get_settings()
    if not settings.sendgrid_webhook_public_key:
        return False
    if signature_header is None and timestamp_header is None:
        return False
    try:
        verify_sendgrid_signature(
            public_key=settings.sendgrid_webhook_public_key,
            payload=raw_body,
            signature_b64=signature_header,
            timestamp=timestamp_header,
            tolerance_seconds=settings.sendgrid_webhook_signature_tolerance_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return True


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


def _map_sendgrid_event_type(value: object) -> str | None:
    name = str(value or "").strip().lower()
    if name == "bounce":
        return "bounced"
    if name in {"unsubscribe", "group_unsubscribe", "spamreport"}:
        return "opt_out"
    return None


def _map_postmark_event_type(record_type: object, payload: dict[str, object]) -> str | None:
    name = str(record_type or "").strip().lower()
    if name == "bounce":
        return "bounced"
    if name in {"spamcomplaint", "spam_complaint"}:
        return "opt_out"
    if name == "subscriptionchange":
        if bool(payload.get("SuppressSending")) or bool(payload.get("suppress_sending")):
            return "opt_out"
    return None


def _map_mailgun_event_type(value: object) -> str | None:
    name = str(value or "").strip().lower()
    if name in {"failed", "bounced"}:
        return "bounced"
    if name in {"unsubscribed", "complained"}:
        return "opt_out"
    return None


def _normalize_sendgrid_events(raw_events: list[object]) -> list[OutreachWebhookEvent]:
    normalized: list[OutreachWebhookEvent] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        event_type = _map_sendgrid_event_type(item.get("event"))
        if not event_type:
            continue
        event_id = item.get("sg_event_id") or item.get("smtp-id")
        email_value = item.get("email")
        normalized.append(
            OutreachWebhookEvent(
                event_id=str(event_id).strip() if event_id else None,
                event_type=event_type,
                email_or_domain=str(email_value).strip().lower() if email_value else None,
                payload=dict(item),
            )
        )
    return normalized


def _normalize_postmark_event(raw: dict[str, object]) -> OutreachWebhookRequest:
    event_type = _map_postmark_event_type(raw.get("RecordType"), raw)
    if not event_type:
        return OutreachWebhookRequest(events=[])
    event_id = raw.get("MessageID") or raw.get("MessageId")
    email_value = raw.get("Email") or raw.get("Recipient")
    return OutreachWebhookRequest(
        events=[
            OutreachWebhookEvent(
                event_id=str(event_id).strip() if event_id else None,
                event_type=event_type,
                email_or_domain=str(email_value).strip().lower() if email_value else None,
                payload=dict(raw),
            )
        ]
    )


def _normalize_mailgun_event(raw_event_data: dict[str, object]) -> OutreachWebhookRequest:
    event_type = _map_mailgun_event_type(raw_event_data.get("event"))
    if not event_type:
        return OutreachWebhookRequest(events=[])
    event_id = raw_event_data.get("id")
    recipient = raw_event_data.get("recipient")
    return OutreachWebhookRequest(
        events=[
            OutreachWebhookEvent(
                event_id=str(event_id).strip() if event_id else None,
                event_type=event_type,
                email_or_domain=str(recipient).strip().lower() if recipient else None,
                payload=dict(raw_event_data),
            )
        ]
    )


def _parse_form_encoded_body(raw_body: bytes) -> OutreachWebhookRequest:
    parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
    event_data_values = parsed.get("event-data") or parsed.get("event_data")
    if not event_data_values:
        raise HTTPException(status_code=400, detail="invalid_body: missing event-data form field")
    event_data_raw = event_data_values[0]
    try:
        event_data = json.loads(event_data_raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid_body: {exc}") from exc
    if not isinstance(event_data, dict):
        raise HTTPException(status_code=400, detail="invalid_body: event-data must be object")
    return _normalize_mailgun_event(event_data)


def _parse_request_body(raw_body: bytes, *, content_type: str | None = None) -> OutreachWebhookRequest:
    content_type_value = (content_type or "").split(";", 1)[0].strip().lower()
    if content_type_value == "application/x-www-form-urlencoded":
        return _parse_form_encoded_body(raw_body)
    try:
        raw = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid_body: {exc}") from exc

    if isinstance(raw, dict) and "events" in raw:
        try:
            return OutreachWebhookRequest.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"invalid_body: {exc}") from exc

    if isinstance(raw, dict) and isinstance(raw.get("event-data"), dict):
        return _normalize_mailgun_event(raw["event-data"])

    if isinstance(raw, dict) and "RecordType" in raw:
        return _normalize_postmark_event(raw)

    if isinstance(raw, list):
        return OutreachWebhookRequest(events=_normalize_sendgrid_events(raw))

    if isinstance(raw, dict):
        provider = str(raw.get("provider") or "").strip().lower()
        provider_events = raw.get("provider_events")
        if provider == "sendgrid" and isinstance(provider_events, list):
            return OutreachWebhookRequest(events=_normalize_sendgrid_events(provider_events))

    raise HTTPException(status_code=400, detail="invalid_body: unsupported webhook payload shape")


@router.post("/outreach-events")
async def ingest_outreach_events(
    request: Request,
    x_webhook_token: str | None = Header(default=None),
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_timestamp: str | None = Header(default=None),
    x_postmark_server_token: str | None = Header(default=None),
    x_twilio_email_event_webhook_signature: str | None = Header(default=None),
    x_twilio_email_event_webhook_timestamp: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    raw_body = await request.body()
    settings = get_settings()
    content_type = request.headers.get("content-type")
    if settings.webhook_signature_secret:
        _verify_webhook_hmac(raw_body, x_webhook_signature, x_webhook_timestamp)
    elif _verify_sendgrid_webhook_signature(
        raw_body,
        signature_header=x_twilio_email_event_webhook_signature,
        timestamp_header=x_twilio_email_event_webhook_timestamp,
    ):
        pass
    elif settings.postmark_webhook_token and x_postmark_server_token is not None:
        _require_postmark_token(x_postmark_server_token)
    elif _verify_mailgun_webhook_signature(raw_body, content_type=content_type):
        pass
    else:
        _require_webhook_secret(x_webhook_token)
    body = _parse_request_body(raw_body, content_type=content_type)

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
