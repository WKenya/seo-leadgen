from celery import Celery

from app.settings import get_settings

settings = get_settings()

celery_app = Celery("seo_lead", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Import task modules so Celery discovers decorated tasks.
from app.tasks import audit, discover, gmail_drafts, notion_sync, summarize  # noqa: E402,F401

