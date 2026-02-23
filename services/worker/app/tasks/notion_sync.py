from app.worker import celery_app


@celery_app.task(name="sync_notion")
def sync_notion(lead_id: str, audit_id: str | None = None, draft_id: str | None = None) -> dict[str, object]:
    return {
        "status": "stub",
        "lead_id": lead_id,
        "audit_id": audit_id,
        "draft_id": draft_id,
    }

