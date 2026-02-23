from app.worker import celery_app


@celery_app.task(name="summarize_and_draft")
def summarize_and_draft(lead_id: str, audit_id: str) -> dict[str, object]:
    return {"status": "stub", "lead_id": lead_id, "audit_id": audit_id}

