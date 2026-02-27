from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import EmailDraft, Lead, OutreachEvent

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _provider_expr():
    return func.lower(func.coalesce(OutreachEvent.payload["provider"].as_string(), ""))


@router.get("/summary")
def metrics_summary(
    provider: str | None = Query(default=None, description="Optional webhook provider filter, e.g. sendgrid|mailgun|postmark"),
    latest_limit: int = Query(default=10, ge=1, le=100),
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
    today_filter = (OutreachEvent.created_at >= start, OutreachEvent.created_at < end)
    provider_column = _provider_expr()

    events_today = int(db.execute(select(func.count()).select_from(OutreachEvent).where(*today_filter)).scalar_one())
    events_today_by_type_rows = db.execute(
        select(OutreachEvent.type, func.count()).where(*today_filter).group_by(OutreachEvent.type)
    ).all()
    events_today_by_type = {str(event_type): int(count) for event_type, count in events_today_by_type_rows}

    provider_rows = db.execute(
        select(provider_column.label("provider"), func.count())
        .where(*today_filter, provider_column != "")
        .group_by(provider_column)
    ).all()
    webhook_events_by_provider_today = {str(provider): int(count) for provider, count in provider_rows}

    provider_type_rows = db.execute(
        select(provider_column.label("provider"), OutreachEvent.type, func.count())
        .where(*today_filter, provider_column != "")
        .group_by(provider_column, OutreachEvent.type)
    ).all()
    webhook_event_types_by_provider_today: dict[str, dict[str, int]] = {}
    for provider_name, event_type, count in provider_type_rows:
        provider_key = str(provider_name)
        provider_bucket = webhook_event_types_by_provider_today.setdefault(provider_key, {})
        provider_bucket[str(event_type)] = int(count)

    latest_event_rows = (
        db.execute(select(OutreachEvent).order_by(OutreachEvent.created_at.desc()).limit(latest_limit)).scalars().all()
    )
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
        webhook_events_today_for_provider = int(
            db.execute(
                select(func.count())
                .select_from(OutreachEvent)
                .where(*today_filter, provider_column == provider_filter)
            ).scalar_one()
        )
        provider_type_filtered_rows = db.execute(
            select(OutreachEvent.type, func.count())
            .where(*today_filter, provider_column == provider_filter)
            .group_by(OutreachEvent.type)
        ).all()
        webhook_event_types_today_for_provider = {
            str(event_type): int(count) for event_type, count in provider_type_filtered_rows
        }
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
        "latest_limit": latest_limit,
        "latest_event_types": list(latest_events),
        "provider_filter": provider_filter,
        "webhook_events_today_for_provider": webhook_events_today_for_provider,
        "webhook_event_types_today_for_provider": webhook_event_types_today_for_provider,
        "latest_event_types_for_provider": latest_event_types_for_provider,
    }
