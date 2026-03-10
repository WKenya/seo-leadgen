from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


_LEAD_STATUS_LABELS = {
    "discovered": "Discovered",
    "audited": "Audited",
    "draft ready": "Draft Ready",
    "approved to send": "Approved to Send",
    "sent": "Sent",
    "replied": "Replied",
    "suppressed": "Suppressed",
}


def _normalize_optional_text(value: object | None, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if lower:
        return text.lower()
    return text


def _normalize_lead_status(value: object | None) -> str:
    normalized = _normalize_optional_text(value)
    if not normalized:
        return ""
    return _LEAD_STATUS_LABELS.get(normalized.lower(), normalized)


class LeadRead(BaseModel):
    id: UUID
    name: str
    category: str | None = None
    source: str | None = None
    place_id: str | None = None
    website_url: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    status: str
    notion_page_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_model(cls, lead: object) -> "LeadRead":
        parsed = cls.model_validate(lead, from_attributes=True)
        parsed.status = _normalize_lead_status(getattr(lead, "status", parsed.status))
        return parsed


class AuditRead(BaseModel):
    id: UUID
    lead_id: UUID
    started_at: datetime | None = None
    finished_at: datetime | None = None
    final_url: str | None = None
    https_ok: bool | None = None
    redirect_chain: object | None = None
    cert_error: str | None = None
    lighthouse_summary: object | None = None
    crawl_summary: object | None = None
    contact_signals: object | None = None
    artifact_index: object | None = None

    @classmethod
    def from_model(cls, audit: object) -> "AuditRead":
        return cls.model_validate(audit, from_attributes=True)


class IssueRead(BaseModel):
    id: UUID
    audit_id: UUID
    kind: str
    severity: int
    title: str
    details: object | None = None

    @classmethod
    def from_model(cls, issue: object) -> "IssueRead":
        return cls.model_validate(issue, from_attributes=True)


class EmailDraftRead(BaseModel):
    id: UUID
    lead_id: UUID
    audit_id: UUID
    subject: str
    body_text: str
    created_at: datetime | None = None
    approved_at: datetime | None = None
    sent_at: datetime | None = None
    gmail_draft_id: str | None = None
    gmail_draft_url: str | None = None

    @classmethod
    def from_model(cls, draft: object) -> "EmailDraftRead":
        return cls.model_validate(draft, from_attributes=True)


class OutreachEventRead(BaseModel):
    id: UUID
    lead_id: UUID
    external_id: str | None = None
    type: str
    payload: object | None = None
    provider: str | None = None
    provider_event_id: str | None = None
    provider_event_name: str | None = None
    provider_event_at: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_model(cls, event: object) -> "OutreachEventRead":
        payload = getattr(event, "payload", None)
        payload_map = payload if isinstance(payload, dict) else {}
        normalized_provider = _normalize_optional_text(getattr(event, "provider", None), lower=True) or _normalize_optional_text(
            payload_map.get("provider"),
            lower=True,
        )
        return cls(
            id=getattr(event, "id"),
            lead_id=getattr(event, "lead_id"),
            external_id=_normalize_optional_text(getattr(event, "external_id", None)),
            type=getattr(event, "type"),
            payload=payload,
            provider=normalized_provider,
            provider_event_id=_normalize_optional_text(payload_map.get("provider_event_id")),
            provider_event_name=_normalize_optional_text(payload_map.get("provider_event_name")),
            provider_event_at=_normalize_optional_text(payload_map.get("provider_event_at")),
            created_at=getattr(event, "created_at", None),
        )


class SuppressionRead(BaseModel):
    id: UUID
    email_or_domain: str
    reason: str
    created_at: datetime | None = None

    @classmethod
    def from_model(cls, suppression: object) -> "SuppressionRead":
        raw_email_or_domain = getattr(suppression, "email_or_domain", "")
        raw_reason = getattr(suppression, "reason", "")
        normalized_email_or_domain = _normalize_optional_text(raw_email_or_domain, lower=True) or str(
            raw_email_or_domain
        ).strip().lower()
        normalized_reason = _normalize_optional_text(raw_reason, lower=True) or str(raw_reason).strip().lower()
        return cls(
            id=getattr(suppression, "id"),
            email_or_domain=normalized_email_or_domain,
            reason=normalized_reason,
            created_at=getattr(suppression, "created_at", None),
        )
