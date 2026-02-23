from app.worker import celery_app


@celery_app.task(name="discover_leads")
def discover_leads(city: str, category: str, radius_meters: int = 15000) -> dict[str, object]:
    return {
        "status": "stub",
        "city": city,
        "category": category,
        "radius_meters": radius_meters,
    }

