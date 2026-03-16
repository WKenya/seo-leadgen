from __future__ import annotations

import json
import re
import secrets
from collections.abc import Mapping
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Lead, OutreachEvent, Suppression
from app.settings import get_settings
from app.webhook_auth import verify_hmac_request, verify_mailgun_signature, verify_sendgrid_signature

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
_EMAIL_OR_DOMAIN_PATTERN = re.compile(r"^[^/@\s]+@[^/@\s]+$")


class OutreachWebhookEvent(BaseModel):
    event_id: str | None = None
    event_type: str  # replied|bounced|opt_out
    lead_id: UUID | None = None
    email_or_domain: str | None = None
    provider: str | None = None
    provider_event_name: str | None = None
    provider_event_at: str | None = None
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
        try:
            parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            return None
        ts = (parsed.get("signature[timestamp]") or parsed.get("timestamp") or [None])[0]
        token = (parsed.get("signature[token]") or parsed.get("token") or [None])[0]
        sig = (parsed.get("signature[signature]") or parsed.get("signature") or [None])[0]
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
    normalized_url = url.strip()
    if not normalized_url:
        return None
    parsed = urlparse(normalized_url if "://" in normalized_url else f"https://{normalized_url}")
    domain = (parsed.hostname or "").strip().lower()
    return domain or None


def _normalize_email_or_domain(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if _EMAIL_OR_DOMAIN_PATTERN.fullmatch(normalized):
        return normalized
    return _domain_from_url(normalized) or normalized


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_suppression_reason(reason: str | None, *, default: str = "manual") -> str:
    normalized = (reason or "").strip().lower()
    return normalized or default


def _first_normalized_email_or_domain(*values: str | None) -> str | None:
    for value in values:
        normalized = _normalize_email_or_domain(value)
        if normalized:
            return normalized
    return None


def _build_lead_domain_fallback_lookup(db: Session) -> dict[str, Lead]:
    lookup: dict[str, Lead] = {}
    for lead in db.execute(
        select(Lead).where((Lead.website_domain.is_not(None)) | (Lead.website_url.is_not(None)))
    ).scalars():
        domain = _domain_from_url(lead.website_domain) or _domain_from_url(lead.website_url)
        if domain:
            lookup.setdefault(domain, lead)
    return lookup


def _find_lead_by_email_or_domain(
    db: Session,
    value: str,
    *,
    domain_fallback_lookup: Mapping[str, Lead] | None = None,
) -> Lead | None:
    normalized = _normalize_email_or_domain(value)
    if not normalized:
        return None
    lead = db.execute(
        select(Lead).where(func.lower(func.trim(func.coalesce(Lead.email, ""))) == normalized)
    ).scalar_one_or_none()
    if lead is not None:
        return lead
    lead = db.execute(
        select(Lead).where(func.lower(func.trim(func.coalesce(Lead.website_domain, ""))) == normalized)
    ).scalar_one_or_none()
    if lead is not None:
        return lead
    if domain_fallback_lookup is not None:
        return domain_fallback_lookup.get(normalized)
    for candidate in db.execute(
        select(Lead).where((Lead.website_domain.is_not(None)) | (Lead.website_url.is_not(None)))
    ).scalars():
        candidate_domain = _domain_from_url(candidate.website_domain) or _domain_from_url(candidate.website_url)
        if candidate_domain == normalized:
            return candidate
    return None


def _prefill_lead_lookup_cache(
    db: Session,
    *,
    normalized_values: set[str],
    domain_fallback_lookup: dict[str, Lead] | None = None,
) -> tuple[dict[str, Lead | None], dict[str, Lead] | None]:
    if not normalized_values:
        return {}, domain_fallback_lookup

    email_expr = func.lower(func.trim(func.coalesce(Lead.email, "")))
    domain_expr = func.lower(func.trim(func.coalesce(Lead.website_domain, "")))

    cache: dict[str, Lead | None] = {}
    ambiguous_email_values: set[str] = set()
    for lead, normalized in db.execute(
        select(Lead, email_expr.label("normalized")).where(email_expr.in_(normalized_values))
    ).all():
        normalized_value = str(normalized or "")
        if not normalized_value:
            continue
        if normalized_value in ambiguous_email_values:
            continue
        if normalized_value in cache:
            ambiguous_email_values.add(normalized_value)
            cache.pop(normalized_value, None)
            continue
        cache[normalized_value] = lead

    domain_prefill_candidates = normalized_values - set(cache) - ambiguous_email_values
    ambiguous_domain_values: set[str] = set()
    for lead, normalized in db.execute(
        select(Lead, domain_expr.label("normalized")).where(domain_expr.in_(domain_prefill_candidates))
    ).all():
        normalized_value = str(normalized or "")
        if not normalized_value:
            continue
        if normalized_value in ambiguous_domain_values:
            continue
        if normalized_value in cache:
            ambiguous_domain_values.add(normalized_value)
            cache.pop(normalized_value, None)
            continue
        cache[normalized_value] = lead

    unresolved = domain_prefill_candidates - set(cache) - ambiguous_domain_values
    if unresolved:
        if domain_fallback_lookup is None:
            domain_fallback_lookup = _build_lead_domain_fallback_lookup(db)
        for normalized in unresolved:
            cache[normalized] = domain_fallback_lookup.get(normalized)

    return cache, domain_fallback_lookup


def _upsert_suppression(
    db: Session,
    *,
    value: str,
    reason: str,
    existing_values: set[str] | None = None,
) -> None:
    normalized_value = _normalize_email_or_domain(value)
    if not normalized_value:
        return
    normalized_reason = _normalize_suppression_reason(reason)
    if existing_values is not None:
        if normalized_value in existing_values:
            return
        db.add(Suppression(email_or_domain=normalized_value, reason=normalized_reason))
        existing_values.add(normalized_value)
        return
    row_id = db.execute(
        select(Suppression.id)
        .where(
            func.lower(func.trim(func.coalesce(Suppression.email_or_domain, ""))) == normalized_value
        )
        .limit(1)
    ).scalar_one_or_none()
    if row_id is None:
        db.add(Suppression(email_or_domain=normalized_value, reason=normalized_reason))


def _map_sendgrid_event_type(value: object) -> str | None:
    name = str(value or "").strip().lower()
    if name in {"bounce", "dropped"}:
        return "bounced"
    if name in {"unsubscribe", "group_unsubscribe", "spamreport", "spam_report"}:
        return "opt_out"
    return None


def _map_postmark_event_type(record_type: object, payload: dict[str, object]) -> str | None:
    name = str(record_type or "").strip().lower()
    if name == "bounce":
        return "bounced"
    if name in {"spamcomplaint", "spam_complaint"}:
        return "opt_out"
    if name == "subscriptionchange":
        if _is_truthy(payload.get("SuppressSending")) or _is_truthy(payload.get("suppress_sending")):
            return "opt_out"
    return None


def _map_mailgun_event_type(value: object, payload: dict[str, object] | None = None) -> str | None:
    name = str(value or "").strip().lower()
    if name == "failed":
        severity = str((payload or {}).get("severity") or "").strip().lower()
        if severity in {"temporary", "temp"}:
            return None
        return "bounced"
    if name == "bounced":
        return "bounced"
    if name in {"unsubscribed", "complained"}:
        return "opt_out"
    return None


def _is_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return False


def _coerce_event_time(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc).isoformat()
        except ValueError:
            return raw
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
                provider="sendgrid",
                provider_event_name=str(item.get("event") or "").strip() or None,
                provider_event_at=_coerce_event_time(item.get("timestamp")),
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
                provider="postmark",
                provider_event_name=str(raw.get("RecordType") or "").strip() or None,
                provider_event_at=(
                    _coerce_event_time(raw.get("ReceivedAt"))
                    or _coerce_event_time(raw.get("BouncedAt"))
                    or _coerce_event_time(raw.get("InactiveAt"))
                    or _coerce_event_time(raw.get("RecordedAt"))
                ),
                payload=dict(raw),
            )
        ]
    )


def _normalize_mailgun_event(raw_event_data: dict[str, object]) -> OutreachWebhookRequest:
    event_type = _map_mailgun_event_type(raw_event_data.get("event"), raw_event_data)
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
                provider="mailgun",
                provider_event_name=str(raw_event_data.get("event") or "").strip() or None,
                provider_event_at=(
                    _coerce_event_time(raw_event_data.get("timestamp"))
                    or _coerce_event_time(raw_event_data.get("event_timestamp"))
                ),
                payload=dict(raw_event_data),
            )
        ]
    )


def _parse_form_encoded_body(raw_body: bytes) -> OutreachWebhookRequest:
    try:
        parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid_body: {exc}") from exc
    if not (parsed.get("event-data") or parsed.get("event_data")):
        if parsed.get("event"):
            legacy_event: dict[str, object] = {}
            for key, values in parsed.items():
                if not values:
                    continue
                legacy_event[key] = values[0]
            if "recipient" in legacy_event and "event" in legacy_event:
                if "id" not in legacy_event:
                    legacy_event["id"] = (
                        legacy_event.get("event-id")
                        or legacy_event.get("event_id")
                        or legacy_event.get("Message-Id")
                        or legacy_event.get("message-id")
                    )
                return _normalize_mailgun_event(legacy_event)

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
    rejected_by_reason: dict[str, int] = {}
    processed_by_type: dict[str, int] = {}
    processed_by_provider: dict[str, int] = {}
    allowed = {"replied", "bounced", "opt_out"}
    suppression_event_types = {"bounced", "opt_out"}
    domain_fallback_lookup: dict[str, Lead] | None = None
    candidate_lead_ids = {item.lead_id for item in body.events if item.lead_id is not None}
    lead_id_lookup_cache: dict[UUID, Lead | None] = (
        {
            **{lead_id: None for lead_id in candidate_lead_ids},
            **{
                lead.id: lead
                for lead in db.execute(select(Lead).where(Lead.id.in_(candidate_lead_ids))).scalars()
            },
        }
        if candidate_lead_ids
        else {}
    )
    candidate_email_or_domain_values = {
        normalized
        for item in body.events
        if item.event_type.strip().lower() in allowed
        for normalized in [_normalize_email_or_domain(item.email_or_domain)]
        if normalized
    }
    lead_lookup_cache, domain_fallback_lookup = _prefill_lead_lookup_cache(
        db,
        normalized_values=candidate_email_or_domain_values,
        domain_fallback_lookup=domain_fallback_lookup,
    )
    suppression_expr = func.lower(func.trim(func.coalesce(Suppression.email_or_domain, "")))
    candidate_suppression_values: set[str] = set()
    for item in body.events:
        event_type = item.event_type.strip().lower()
        if event_type not in suppression_event_types:
            continue
        normalized = _normalize_email_or_domain(item.email_or_domain)
        if normalized:
            candidate_suppression_values.add(normalized)
            continue
        if item.lead_id is None:
            continue
        lead = lead_id_lookup_cache.get(item.lead_id)
        if lead is None:
            continue
        suppression_value = _first_normalized_email_or_domain(
            lead.email,
            lead.website_domain,
            _domain_from_url(lead.website_url),
        )
        if suppression_value:
            candidate_suppression_values.add(suppression_value)
    seen_suppression_values = (
        set(
            db.scalars(
                select(suppression_expr).where(suppression_expr.in_(candidate_suppression_values))
            ).all()
        )
        if candidate_suppression_values
        else set()
    )
    external_id_expr = func.trim(func.coalesce(OutreachEvent.external_id, ""))
    candidate_external_ids = {
        external_id
        for item in body.events
        if item.event_type.strip().lower() in allowed
        for external_id in [((item.event_id or "").strip())]
        if external_id
    }
    seen_external_ids = (
        set(db.scalars(select(external_id_expr).where(external_id_expr.in_(candidate_external_ids))).all())
        if candidate_external_ids
        else set()
    )

    for item in body.events:
        event_type = item.event_type.strip().lower()
        if event_type not in allowed:
            reason = "invalid_event_type"
            rejected.append({"reason": reason, "event_type": item.event_type})
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
            continue
        external_id = (item.event_id or "").strip() or None
        if external_id and external_id in seen_external_ids:
            duplicates += 1
            continue

        lead = None
        if item.lead_id:
            lead = lead_id_lookup_cache.get(item.lead_id)
        if lead is None and item.email_or_domain:
            normalized_lookup = _normalize_email_or_domain(item.email_or_domain)
            if normalized_lookup:
                if normalized_lookup not in lead_lookup_cache:
                    if domain_fallback_lookup is None:
                        domain_fallback_lookup = _build_lead_domain_fallback_lookup(db)
                    lead_lookup_cache[normalized_lookup] = _find_lead_by_email_or_domain(
                        db,
                        normalized_lookup,
                        domain_fallback_lookup=domain_fallback_lookup,
                    )
                lead = lead_lookup_cache[normalized_lookup]
        if lead is None:
            reason = "lead_not_found"
            rejected.append(
                {
                    "reason": reason,
                    "lead_id": str(item.lead_id) if item.lead_id else None,
                    "email_or_domain": item.email_or_domain,
                }
            )
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
            continue

        lead_domain = _domain_from_url(lead.website_domain) or _domain_from_url(lead.website_url)
        if lead_domain and domain_fallback_lookup is not None:
            domain_fallback_lookup.setdefault(lead_domain, lead)

        provider_value = (item.provider or "").strip().lower() or None
        provider_event_name = _normalize_optional_text(item.provider_event_name)
        provider_event_at = _normalize_optional_text(item.provider_event_at)
        suppression_value = _first_normalized_email_or_domain(
            item.email_or_domain,
            lead.email,
            lead.website_domain,
            _domain_from_url(lead.website_url),
        )
        if event_type in suppression_event_types and suppression_value:
            if suppression_value not in seen_suppression_values:
                _upsert_suppression(
                    db,
                    value=suppression_value,
                    reason=event_type,
                    existing_values=seen_suppression_values,
                )
            lead.status = "Suppressed"
        elif event_type == "replied":
            lead.status = "Replied"

        db.add(
            OutreachEvent(
                lead_id=lead.id,
                external_id=external_id,
                provider=provider_value,
                type=event_type,
                payload={
                    "source": "webhook",
                    "provider": provider_value,
                    "provider_event_id": external_id if provider_value else None,
                    "provider_event_name": provider_event_name,
                    "provider_event_at": provider_event_at,
                    "email_or_domain": suppression_value or None,
                    "payload": item.payload,
                },
            )
        )
        if external_id:
            seen_external_ids.add(external_id)
        processed += 1
        processed_by_type[event_type] = processed_by_type.get(event_type, 0) + 1
        if provider_value:
            processed_by_provider[provider_value] = processed_by_provider.get(provider_value, 0) + 1

    db.commit()
    return {
        "status": "ok",
        "processed": processed,
        "processed_by_type": processed_by_type,
        "processed_by_provider": processed_by_provider,
        "duplicates": duplicates,
        "rejected": rejected,
        "rejected_by_reason": rejected_by_reason,
    }
