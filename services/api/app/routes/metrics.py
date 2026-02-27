from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EmailDraft, Lead, OutreachEvent

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/summary")
def metrics_summary(
    provider: str | None = Query(default=None, description="Optional webhook provider filter, e.g. sendgrid|mailgun|postmark"),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    provider_filter = (provider or "").strip().lower() or None

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
    webhook_event_types_by_provider_today: dict[str, dict[str, int]] = {}
    events_today_by_type: dict[str, int] = {}
    for event in event_rows_today:
        events_today_by_type[event.type] = events_today_by_type.get(event.type, 0) + 1
        provider = str((event.payload or {}).get("provider") or "").strip().lower()
        if not provider:
            continue
        webhook_events_by_provider_today[provider] = webhook_events_by_provider_today.get(provider, 0) + 1
        provider_types = webhook_event_types_by_provider_today.setdefault(provider, {})
        provider_types[event.type] = provider_types.get(event.type, 0) + 1

    latest_event_rows = db.execute(select(OutreachEvent).order_by(OutreachEvent.created_at.desc()).limit(10)).scalars().all()
    latest_events = [event.type for event in latest_event_rows]
    latest_webhook_providers: list[str] = []
    seen_providers: set[str] = set()
    for event in latest_event_rows:
        provider = str((event.payload or {}).get("provider") or "").strip().lower()
        if not provider or provider in seen_providers:
            continue
        latest_webhook_providers.append(provider)
        seen_providers.add(provider)

    webhook_events_today_for_provider: int | None = None
    webhook_event_types_today_for_provider: dict[str, int] | None = None
    latest_event_types_for_provider: list[str] | None = None
    if provider_filter:
        filtered_today = [
            event for event in event_rows_today if str((event.payload or {}).get("provider") or "").strip().lower() == provider_filter
        ]
        webhook_events_today_for_provider = len(filtered_today)
        provider_types: dict[str, int] = {}
        for event in filtered_today:
            provider_types[event.type] = provider_types.get(event.type, 0) + 1
        webhook_event_types_today_for_provider = provider_types
        latest_event_types_for_provider = [
            event.type
            for event in latest_event_rows
            if str((event.payload or {}).get("provider") or "").strip().lower() == provider_filter
        ]

    return {
        "as_of": now.isoformat(),
        "leads_by_status": leads_by_status,
        "drafts_total": drafts_total,
        "drafts_approved": drafts_approved,
        "drafts_sent_today": drafts_sent_today,
        "events_today": events_today,
        "events_today_by_type": events_today_by_type,
        "webhook_events_by_provider_today": webhook_events_by_provider_today,
        "webhook_event_types_by_provider_today": webhook_event_types_by_provider_today,
        "latest_webhook_providers": latest_webhook_providers,
        "latest_event_types": list(latest_events),
        "provider_filter": provider_filter,
        "webhook_events_today_for_provider": webhook_events_today_for_provider,
        "webhook_event_types_today_for_provider": webhook_event_types_today_for_provider,
        "latest_event_types_for_provider": latest_event_types_for_provider,
    }
