from __future__ import annotations

from uuid import UUID

from app.db import SessionLocal
from app.models import EmailDraft, Lead, OutreachEvent
from app.outreach.policy import remaining_daily_send_cap
from app.settings import get_settings
from app.worker import celery_app


@celery_app.task(name="create_gmail_draft")
def create_gmail_draft(draft_id: str) -> dict[str, object]:
    settings = get_settings()

    with SessionLocal() as session:
        draft = session.get(EmailDraft, UUID(draft_id))
        if draft is None:
            raise RuntimeError(f"draft not found: {draft_id}")
        lead = session.get(Lead, draft.lead_id)
        if lead is None:
            raise RuntimeError(f"lead not found for draft: {draft_id}")

        # MVP fallback: keep manual send flow unless Gmail OAuth creds are configured.
        gmail_mode = (
            "api"
            if settings.gmail_oauth_client_id and settings.gmail_oauth_client_secret and settings.gmail_oauth_refresh_token
            else "manual"
        )
        if gmail_mode == "manual":
            draft.gmail_draft_url = None
        else:
            # Placeholder until Gmail API integration is implemented.
            draft.gmail_draft_url = None

        cap_remaining = remaining_daily_send_cap(session, cap=settings.daily_send_cap)
        session.add(
            OutreachEvent(
                lead_id=lead.id,
                type="drafted",
                payload={
                    "draft_id": str(draft.id),
                    "gmail_mode": gmail_mode,
                    "gmail_draft_url": draft.gmail_draft_url,
                    "daily_send_cap": settings.daily_send_cap,
                    "cap_remaining": cap_remaining,
                },
            )
        )
        session.commit()

        audit_id = str(draft.audit_id)
        lead_id = str(lead.id)

    celery_app.send_task("sync_notion", kwargs={"lead_id": lead_id, "audit_id": audit_id, "draft_id": draft_id})

    return {
        "status": "ok",
        "draft_id": draft_id,
        "gmail_mode": gmail_mode,
        "gmail_draft_url": None,
    }
