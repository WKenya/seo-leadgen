from celery import Celery
from celery.schedules import crontab

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

if settings.discovery_categories:
    celery_app.conf.beat_schedule = {
        f"discover-{category.lower().replace(' ', '-')}-daily": {
            "task": "discover_leads",
            "schedule": crontab(
                hour=settings.discovery_schedule_hour_utc,
                minute=settings.discovery_schedule_minute_utc,
            ),
            "kwargs": {
                "city": settings.discovery_city,
                "category": category,
                "radius_meters": settings.discovery_radius_meters,
                "limit": settings.discovery_limit_per_category,
            },
        }
        for category in settings.discovery_categories
    }

# Import task modules so Celery discovers decorated tasks.
from app.tasks import audit, discover, gmail_drafts, notion_sync, summarize, suppression  # noqa: E402,F401
