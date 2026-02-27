from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


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
        return cls.model_validate(lead, from_attributes=True)


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
        return cls(
            id=getattr(event, "id"),
            lead_id=getattr(event, "lead_id"),
            external_id=getattr(event, "external_id", None),
            type=getattr(event, "type"),
            payload=payload,
            provider=str(payload_map.get("provider")) if payload_map.get("provider") is not None else None,
            provider_event_id=(
                str(payload_map.get("provider_event_id")) if payload_map.get("provider_event_id") is not None else None
            ),
            provider_event_name=(
                str(payload_map.get("provider_event_name"))
                if payload_map.get("provider_event_name") is not None
                else None
            ),
            provider_event_at=(
                str(payload_map.get("provider_event_at")) if payload_map.get("provider_event_at") is not None else None
            ),
            created_at=getattr(event, "created_at", None),
        )


class SuppressionRead(BaseModel):
    id: UUID
    email_or_domain: str
    reason: str
    created_at: datetime | None = None

    @classmethod
    def from_model(cls, suppression: object) -> "SuppressionRead":
        return cls.model_validate(suppression, from_attributes=True)
