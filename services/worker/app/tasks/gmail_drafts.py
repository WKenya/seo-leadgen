from app.worker import celery_app


@celery_app.task(name="create_gmail_draft")
def create_gmail_draft(draft_id: str) -> dict[str, object]:
    return {"status": "stub", "draft_id": draft_id}

