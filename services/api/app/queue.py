from celery import Celery

from app.settings import get_settings

settings = get_settings()

celery_client = Celery("seo_lead_api", broker=settings.redis_url, backend=settings.redis_url)

