from app.worker import celery_app


@celery_app.task(name="audit_lead")
def audit_lead(lead_id: str) -> dict[str, object]:
    return {"status": "stub", "lead_id": lead_id}

