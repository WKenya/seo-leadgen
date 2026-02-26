from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EmailDraft, Lead, OutreachEvent

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary")
def metrics_summary(db: Session = Depends(get_db)) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    status_rows = db.execute(select(Lead.status, func.count()).group_by(Lead.status).order_by(Lead.status)).all()
    leads_by_status = {str(status or "Unknown"): int(count) for status, count in status_rows}

    drafts_total = int(db.execute(select(func.count()).select_from(EmailDraft)).scalar_one())
    drafts_approved = int(
        db.execute(select(func.count()).select_from(EmailDraft).where(EmailDraft.approved_at.is_not(None))).scalar_one()
    )
    drafts_sent_today = int(
        db.execute(
            select(func.count()).select_from(EmailDraft).where(EmailDraft.sent_at >= start, EmailDraft.sent_at < end)
        ).scalar_one()
    )
    events_today = int(
        db.execute(
            select(func.count()).select_from(OutreachEvent).where(OutreachEvent.created_at >= start, OutreachEvent.created_at < end)
        ).scalar_one()
    )
    event_rows_today = (
        db.execute(select(OutreachEvent).where(OutreachEvent.created_at >= start, OutreachEvent.created_at < end))
        .scalars()
        .all()
    )
    webhook_events_by_provider_today: dict[str, int] = {}
    for event in event_rows_today:
        provider = str((event.payload or {}).get("provider") or "").strip().lower()
        if not provider:
            continue
        webhook_events_by_provider_today[provider] = webhook_events_by_provider_today.get(provider, 0) + 1

    latest_events = (
        db.execute(select(OutreachEvent.type).order_by(OutreachEvent.created_at.desc()).limit(10)).scalars().all()
    )
    return {
        "as_of": now.isoformat(),
        "leads_by_status": leads_by_status,
        "drafts_total": drafts_total,
        "drafts_approved": drafts_approved,
        "drafts_sent_today": drafts_sent_today,
        "events_today": events_today,
        "webhook_events_by_provider_today": webhook_events_by_provider_today,
        "latest_event_types": list(latest_events),
    }
