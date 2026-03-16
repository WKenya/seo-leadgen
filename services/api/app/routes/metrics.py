from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, select
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


def _is_failure_event_type(event_type: str) -> bool:
    normalized = str(event_type or "").strip().lower()
    if not normalized:
        return False
    return (
        normalized == "bounced"
        or "blocked" in normalized
        or "failed" in normalized
        or "skipped" in normalized
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

    (
        drafts_total_raw,
        drafts_approved_raw,
        drafts_created_today_raw,
        drafts_sent_today_raw,
    ) = db.execute(
        select(
            func.count(EmailDraft.id),
            func.sum(case((EmailDraft.approved_at.is_not(None), 1), else_=0)),
            func.sum(case((and_(EmailDraft.created_at >= start, EmailDraft.created_at < end), 1), else_=0)),
            func.sum(case((and_(EmailDraft.sent_at >= start, EmailDraft.sent_at < end), 1), else_=0)),
        )
    ).one()
    drafts_total = int(drafts_total_raw or 0)
    drafts_approved = int(drafts_approved_raw or 0)
    drafts_created_today = int(drafts_created_today_raw or 0)
    drafts_sent_today = int(drafts_sent_today_raw or 0)
    audits_today = int(
        db.execute(select(func.count()).select_from(Audit).where(Audit.started_at >= start, Audit.started_at < end)).scalar_one()
    )
    today_filter = (OutreachEvent.created_at >= start, OutreachEvent.created_at < end)
    provider_column = _provider_expr()
    event_type_column = _event_type_expr()

    events_today_by_type_rows = db.execute(
        select(event_type_column.label("event_type"), func.count()).where(*today_filter).group_by(event_type_column)
    ).all()
    events_today = sum(int(count) for _event_type, count in events_today_by_type_rows)
    events_today_by_type = {
        str(event_type): int(count) for event_type, count in events_today_by_type_rows if str(event_type or "")
    }
    failures_today_by_type = {
        event_type: count
        for event_type, count in events_today_by_type.items()
        if _is_failure_event_type(event_type)
    }
    failures_today = sum(failures_today_by_type.values())

    provider_type_rows = db.execute(
        select(provider_column.label("provider"), event_type_column.label("event_type"), func.count())
        .where(*today_filter, provider_column != "")
        .group_by(provider_column, event_type_column)
    ).all()
    webhook_events_by_provider_today: dict[str, int] = {}
    webhook_event_types_by_provider_today: dict[str, dict[str, int]] = {}
    for provider_name, event_type, count in provider_type_rows:
        provider_key = str(provider_name)
        webhook_events_by_provider_today[provider_key] = webhook_events_by_provider_today.get(provider_key, 0) + int(count)
        if not str(event_type or ""):
            continue
        provider_bucket = webhook_event_types_by_provider_today.setdefault(provider_key, {})
        provider_bucket[str(event_type)] = int(count)

    latest_event_rows = db.execute(
        select(event_type_column.label("event_type"), provider_column.label("provider"))
        .where(event_type_column != "")
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
        webhook_events_today_for_provider = webhook_events_by_provider_today.get(provider_filter, 0)
        webhook_event_types_today_for_provider = dict(webhook_event_types_by_provider_today.get(provider_filter, {}))
        webhook_failure_types_today_for_provider = {
            event_type: count
            for event_type, count in webhook_event_types_today_for_provider.items()
            if _is_failure_event_type(event_type)
        }
        webhook_failures_today_for_provider = sum(webhook_failure_types_today_for_provider.values())
        latest_event_types_for_provider = [
            event_type
            for event_type, in db.execute(
                select(event_type_column.label("event_type"))
                .where(provider_column == provider_filter, event_type_column != "")
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
