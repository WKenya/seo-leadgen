from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Audit, EmailDraft, Lead, OutreachEvent

router = APIRouter(prefix="/metrics", tags=["metrics"])

_STATUS_LABELS = {
    "discovered": "Discovered",
    "audited": "Audited",
    "draft ready": "Draft Ready",
    "approved to send": "Approved to Send",
    "sent": "Sent",
    "replied": "Replied",
    "suppressed": "Suppressed",
}


def _provider_expr():
    provider_source = func.coalesce(
        func.nullif(func.trim(func.coalesce(OutreachEvent.provider, "")), ""),
        OutreachEvent.payload["provider"].as_string(),
        "",
    )
    return func.lower(
        func.trim(
            provider_source
        )
    )


def _event_type_expr():
    return func.lower(func.trim(func.coalesce(OutreachEvent.type, "")))


def _status_expr():
    return func.lower(func.trim(func.coalesce(Lead.status, "")))


def _status_label(status: str) -> str:
    if not status:
        return "Unknown"
    return _STATUS_LABELS.get(status, status)


def _failure_event_filter():
    event_type = _event_type_expr()
    return or_(
        event_type == "bounced",
        event_type.like("%blocked%"),
        event_type.like("%failed%"),
        event_type.like("%skipped%"),
    )


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

    status_column = _status_expr()
    status_rows = db.execute(select(status_column.label("status"), func.count()).group_by(status_column).order_by(status_column)).all()
    leads_by_status = {_status_label(str(status or "")): int(count) for status, count in status_rows}

    drafts_total = int(db.execute(select(func.count()).select_from(EmailDraft)).scalar_one())
    drafts_approved = int(
        db.execute(select(func.count()).select_from(EmailDraft).where(EmailDraft.approved_at.is_not(None))).scalar_one()
    )
    drafts_created_today = int(
        db.execute(
            select(func.count()).select_from(EmailDraft).where(EmailDraft.created_at >= start, EmailDraft.created_at < end)
        ).scalar_one()
    )
    drafts_sent_today = int(
        db.execute(
            select(func.count()).select_from(EmailDraft).where(EmailDraft.sent_at >= start, EmailDraft.sent_at < end)
        ).scalar_one()
    )
    audits_today = int(
        db.execute(select(func.count()).select_from(Audit).where(Audit.started_at >= start, Audit.started_at < end)).scalar_one()
    )
    today_filter = (OutreachEvent.created_at >= start, OutreachEvent.created_at < end)
    provider_column = _provider_expr()
    event_type_column = _event_type_expr()

    events_today = int(db.execute(select(func.count()).select_from(OutreachEvent).where(*today_filter)).scalar_one())
    events_today_by_type_rows = db.execute(
        select(event_type_column.label("event_type"), func.count()).where(*today_filter).group_by(event_type_column)
    ).all()
    events_today_by_type = {
        str(event_type): int(count) for event_type, count in events_today_by_type_rows if str(event_type or "")
    }
    failure_filter = _failure_event_filter()
    failures_today_by_type_rows = db.execute(
        select(event_type_column.label("event_type"), func.count())
        .where(*today_filter, failure_filter)
        .group_by(event_type_column)
    ).all()
    failures_today_by_type = {
        str(event_type): int(count) for event_type, count in failures_today_by_type_rows if str(event_type or "")
    }
    failures_today = sum(failures_today_by_type.values())

    provider_rows = db.execute(
        select(provider_column.label("provider"), func.count())
        .where(*today_filter, provider_column != "")
        .group_by(provider_column)
    ).all()
    webhook_events_by_provider_today = {str(provider): int(count) for provider, count in provider_rows}

    provider_type_rows = db.execute(
        select(provider_column.label("provider"), event_type_column.label("event_type"), func.count())
        .where(*today_filter, provider_column != "")
        .group_by(provider_column, event_type_column)
    ).all()
    webhook_event_types_by_provider_today: dict[str, dict[str, int]] = {}
    for provider_name, event_type, count in provider_type_rows:
        if not str(event_type or ""):
            continue
        provider_key = str(provider_name)
        provider_bucket = webhook_event_types_by_provider_today.setdefault(provider_key, {})
        provider_bucket[str(event_type)] = int(count)

    latest_event_rows = db.execute(
        select(event_type_column.label("event_type"), provider_column.label("provider"))
        .order_by(OutreachEvent.created_at.desc())
        .limit(latest_limit)
    ).all()
    latest_events = [event_type for event_type, _provider in latest_event_rows if str(event_type or "")]
    latest_webhook_providers: list[str] = []
    seen_providers: set[str] = set()
    for _event_type, provider_name in latest_event_rows:
        provider = str(provider_name or "").strip().lower()
        if not provider or provider in seen_providers:
            continue
        latest_webhook_providers.append(provider)
        seen_providers.add(provider)

    webhook_events_today_for_provider: int | None = None
    webhook_event_types_today_for_provider: dict[str, int] | None = None
    webhook_failures_today_for_provider: int | None = None
    webhook_failure_types_today_for_provider: dict[str, int] | None = None
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
            select(event_type_column.label("event_type"), func.count())
            .where(*today_filter, provider_column == provider_filter)
            .group_by(event_type_column)
        ).all()
        webhook_event_types_today_for_provider = {
            str(event_type): int(count) for event_type, count in provider_type_filtered_rows if str(event_type or "")
        }
        provider_failure_rows = db.execute(
            select(event_type_column.label("event_type"), func.count())
            .where(*today_filter, provider_column == provider_filter, failure_filter)
            .group_by(event_type_column)
        ).all()
        webhook_failure_types_today_for_provider = {
            str(event_type): int(count) for event_type, count in provider_failure_rows if str(event_type or "")
        }
        webhook_failures_today_for_provider = sum(webhook_failure_types_today_for_provider.values())
        latest_event_types_for_provider = [
            event_type
            for event_type, in db.execute(
                select(event_type_column.label("event_type"))
                .where(provider_column == provider_filter)
                .order_by(OutreachEvent.created_at.desc())
                .limit(latest_limit)
            ).all()
            if str(event_type or "")
        ]

    return {
        "as_of": now.isoformat(),
        "leads_by_status": leads_by_status,
        "drafts_total": drafts_total,
        "drafts_approved": drafts_approved,
        "drafts_created_today": drafts_created_today,
        "drafts_sent_today": drafts_sent_today,
        "audits_today": audits_today,
        "events_today": events_today,
        "events_today_by_type": events_today_by_type,
        "failures_today": failures_today,
        "failures_today_by_type": failures_today_by_type,
        "webhook_events_by_provider_today": webhook_events_by_provider_today,
        "webhook_event_types_by_provider_today": webhook_event_types_by_provider_today,
        "latest_webhook_providers": latest_webhook_providers,
        "latest_limit": latest_limit,
        "latest_event_types": list(latest_events),
        "provider_filter": provider_filter,
        "webhook_events_today_for_provider": webhook_events_today_for_provider,
        "webhook_event_types_today_for_provider": webhook_event_types_today_for_provider,
        "webhook_failures_today_for_provider": webhook_failures_today_for_provider,
        "webhook_failure_types_today_for_provider": webhook_failure_types_today_for_provider,
        "latest_event_types_for_provider": latest_event_types_for_provider,
    }
