from __future__ import annotations

import re
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Lead, OutreachEvent, Suppression
from app.tasks.task_failures import log_task_failure_for_lead
from app.worker import celery_app

_EMAIL_OR_DOMAIN_PATTERN = re.compile(r"^[^/@\s]+@[^/@\s]+$")


def _domain_from_url(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
    return (parsed.hostname or "").strip().lower() or None


def _normalize_suppression_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if _EMAIL_OR_DOMAIN_PATTERN.fullmatch(normalized):
        return normalized
    return _domain_from_url(normalized) or normalized


def _lead_suppression_key(lead: Lead) -> str | None:
    normalized_email = _normalize_suppression_value(lead.email)
    if normalized_email:
        return normalized_email
    normalized_domain = _normalize_suppression_value(lead.website_domain)
    if normalized_domain:
        return normalized_domain
    return _normalize_suppression_value(lead.website_url)


@celery_app.task(name="apply_suppression")
def apply_suppression(lead_id: str, value: str | None = None, reason: str = "manual") -> dict[str, object]:
    try:
        lead_uuid = UUID(lead_id)
    except ValueError as exc:
        raise RuntimeError(f"invalid lead_id: {lead_id}") from exc

    try:
        with SessionLocal() as session:
            lead = session.get(Lead, lead_uuid)
            if lead is None:
                raise RuntimeError(f"lead not found: {lead_id}")

            suppression_value = _normalize_suppression_value(value) or _lead_suppression_key(lead)
            if not suppression_value:
                return {"status": "missing_target", "lead_id": lead_id}

            normalized_reason = (reason or "").strip().lower() or "manual"
            existing = session.execute(
                select(Suppression.id)
                .where(func.lower(func.trim(func.coalesce(Suppression.email_or_domain, ""))) == suppression_value)
                .limit(1)
            ).scalar_one_or_none()
            created = existing is None
            if created:
                session.add(Suppression(email_or_domain=suppression_value, reason=normalized_reason))

            lead.status = "Suppressed"
            session.add(
                OutreachEvent(
                    lead_id=lead.id,
                    type="suppression_applied",
                    payload={"value": suppression_value, "reason": normalized_reason, "source": "task"},
                )
            )
            session.commit()
        return {"status": "ok", "lead_id": lead_id, "value": suppression_value, "reason": normalized_reason, "created": created}
    except Exception as exc:  # noqa: BLE001
        log_task_failure_for_lead(
            lead_id=lead_id,
            task_name="apply_suppression",
            error=exc,
            context={"value": value, "reason": reason},
        )
        raise
