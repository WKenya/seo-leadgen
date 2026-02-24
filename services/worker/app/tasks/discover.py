from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select

from app.db import SessionLocal
from app.discovery.google_places import GooglePlacesClient
from app.models import Lead, Suppression
from app.settings import get_settings
from app.worker import celery_app


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _find_existing_lead(session, *, place_id: str, website_url: str) -> Lead | None:
    lead = session.execute(select(Lead).where(Lead.place_id == place_id)).scalar_one_or_none()
    if lead is not None:
        return lead

    # Fallback dedupe by domain until we add a persisted normalized-domain column.
    target_domain = _domain(website_url)
    for candidate in session.execute(select(Lead).where(Lead.website_url.is_not(None))).scalars():
        if _domain(candidate.website_url) == target_domain:
            return candidate
    return None


def _suppression_values(session) -> set[str]:
    return {
        (row.email_or_domain or "").lower()
        for row in session.execute(select(Suppression)).scalars()
        if row.email_or_domain
    }


@celery_app.task(name="discover_leads")
def discover_leads(city: str, category: str, radius_meters: int = 15000, limit: int | None = None) -> dict[str, object]:
    settings = get_settings()
    if not settings.google_places_api_key:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured")

    client = GooglePlacesClient(settings.google_places_api_key)
    effective_limit = max(1, min(int(limit or settings.discovery_limit_per_category), 60))
    discovered = client.discover_leads(
        city=city,
        category=category,
        limit=effective_limit,
        radius_meters=radius_meters,
    )

    created = 0
    updated = 0
    skipped = 0
    suppressed = 0
    notion_sync_lead_ids: list[str] = []
    with SessionLocal() as session:
        suppression_values = _suppression_values(session)
        for item in discovered:
            lead_domain = _domain(item.website_url)
            is_suppressed = lead_domain in suppression_values
            lead = _find_existing_lead(
                session,
                place_id=item.place_id,
                website_url=item.website_url,
            )
            if lead is None:
                lead = Lead(
                    name=item.name,
                    category=category,
                    source="google_places",
                    place_id=item.place_id,
                    website_url=item.website_url,
                    address=item.address,
                    phone=item.phone,
                    status="Suppressed" if is_suppressed else "Discovered",
                )
                session.add(lead)
                session.flush()
                created += 1
                if is_suppressed:
                    suppressed += 1
                notion_sync_lead_ids.append(str(lead.id))
                continue

            changed = False
            for attr, value in {
                "name": item.name,
                "category": category,
                "source": "google_places",
                "place_id": item.place_id,
                "website_url": item.website_url,
                "address": item.address,
                "phone": item.phone,
            }.items():
                if value and getattr(lead, attr) != value:
                    setattr(lead, attr, value)
                    changed = True
            desired_status = "Suppressed" if is_suppressed else lead.status
            if desired_status != lead.status:
                lead.status = desired_status
                changed = True
            if changed:
                updated += 1
                notion_sync_lead_ids.append(str(lead.id))
            else:
                skipped += 1
            if is_suppressed:
                suppressed += 1

        session.commit()

    for lead_id in notion_sync_lead_ids:
        celery_app.send_task("sync_notion", kwargs={"lead_id": lead_id})

    return {
        "status": "ok",
        "city": city,
        "category": category,
        "radius_meters_requested": radius_meters,
        "limit_requested": effective_limit,
        "discovered_count": len(discovered),
        "created": created,
        "updated": updated,
        "unchanged": skipped,
        "suppressed_matches": suppressed,
        "queued_notion_sync": len(notion_sync_lead_ids),
        "note": "text search implementation; radius currently informational",
    }
