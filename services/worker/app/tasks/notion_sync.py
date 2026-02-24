from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.integrations.notion_leads import NotionLeadSyncClient, lead_page_properties
from app.models import Audit, EmailDraft, Lead, OutreachEvent
from app.settings import get_settings
from app.worker import celery_app


@celery_app.task(name="sync_notion")
def sync_notion(lead_id: str, audit_id: str | None = None, draft_id: str | None = None) -> dict[str, object]:
    settings = get_settings()

    with SessionLocal() as session:
        lead = session.get(Lead, UUID(lead_id))
        if lead is None:
            raise RuntimeError(f"lead not found: {lead_id}")

        audit = session.get(Audit, UUID(audit_id)) if audit_id else None
        if audit is None and audit_id is None:
            audit = (
                session.execute(select(Audit).where(Audit.lead_id == lead.id).order_by(Audit.finished_at.desc()))
                .scalars()
                .first()
            )

        draft = session.get(EmailDraft, UUID(draft_id)) if draft_id else None
        if draft is None and draft_id is None:
            draft = (
                session.execute(
                    select(EmailDraft).where(EmailDraft.lead_id == lead.id).order_by(EmailDraft.created_at.desc())
                )
                .scalars()
                .first()
            )

        payload_preview = lead_page_properties(
            lead=lead,
            audit=audit,
            draft=draft,
            public_api_base_url=settings.public_api_base_url,
        )
        notion_status = "skipped"
        page_id = lead.notion_page_id
        sync_error = None
        if settings.notion_token and settings.notion_database_id:
            try:
                client = NotionLeadSyncClient(settings.notion_token, settings.notion_database_id)
                page_id = client.upsert_lead_page(
                    lead=lead,
                    audit=audit,
                    draft=draft,
                    public_api_base_url=settings.public_api_base_url,
                )
                lead.notion_page_id = page_id
                notion_status = "synced"
            except Exception as exc:  # noqa: BLE001
                notion_status = "error"
                sync_error = str(exc)

        session.add(
            OutreachEvent(
                lead_id=lead.id,
                type="notion_sync",
                payload={
                    "status": notion_status,
                    "audit_id": audit_id,
                    "draft_id": draft_id,
                    "page_id": page_id,
                    "property_keys": sorted(payload_preview.keys()),
                    "error": sync_error,
                },
            )
        )
        session.commit()

    return {
        "status": notion_status,
        "lead_id": lead_id,
        "audit_id": audit_id,
        "draft_id": draft_id,
        "notion_page_id": page_id,
        "error": sync_error,
    }
