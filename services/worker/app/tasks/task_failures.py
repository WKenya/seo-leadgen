from __future__ import annotations

from uuid import UUID

from app.db import SessionLocal
from app.models import EmailDraft, Lead, OutreachEvent


def _context_payload(context: dict[str, object] | None) -> dict[str, object] | None:
    if not context:
        return None
    return {str(key): value for key, value in context.items() if value is not None}


def _record_failure_for_lead(
    *,
    lead: Lead,
    task_name: str,
    error: Exception | str,
    context: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "task_name": task_name,
        "error": str(error),
    }
    context_payload = _context_payload(context)
    if context_payload is not None:
        payload["context"] = context_payload
    with SessionLocal() as session:
        session.add(OutreachEvent(lead_id=lead.id, type="task_failed", payload=payload))
        session.commit()


def log_task_failure_for_lead(
    *,
    lead_id: str | UUID | None,
    task_name: str,
    error: Exception | str,
    context: dict[str, object] | None = None,
) -> bool:
    if not lead_id:
        return False
    try:
        lead_uuid = UUID(str(lead_id))
    except ValueError:
        return False
    try:
        with SessionLocal() as session:
            lead = session.get(Lead, lead_uuid)
            if lead is None:
                return False
        _record_failure_for_lead(lead=lead, task_name=task_name, error=error, context=context)
    except Exception:  # noqa: BLE001
        return False
    return True


def log_task_failure_for_draft(
    *,
    draft_id: str | UUID | None,
    task_name: str,
    error: Exception | str,
    context: dict[str, object] | None = None,
) -> bool:
    if not draft_id:
        return False
    try:
        draft_uuid = UUID(str(draft_id))
    except ValueError:
        return False
    try:
        with SessionLocal() as session:
            draft = session.get(EmailDraft, draft_uuid)
            if draft is None:
                return False
            lead = session.get(Lead, draft.lead_id)
            if lead is None:
                return False
        _record_failure_for_lead(lead=lead, task_name=task_name, error=error, context=context)
    except Exception:  # noqa: BLE001
        return False
    return True
