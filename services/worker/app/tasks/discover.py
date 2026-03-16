from __future__ import annotations

from collections.abc import Mapping
import re
from urllib.parse import urlparse

from sqlalchemy import func, select

from app.db import SessionLocal
from app.discovery.google_places import GooglePlacesClient
from app.models import Lead, Suppression
from app.settings import get_settings
from app.worker import celery_app

_EMAIL_OR_DOMAIN_PATTERN = re.compile(r"^[^/@\s]+@[^/@\s]+$")


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    normalized_url = url.strip()
    if not normalized_url:
        return None
    parsed = urlparse(normalized_url if "://" in normalized_url else f"https://{normalized_url}")
    return (parsed.hostname or "").strip().lower() or None


def _normalize_suppression_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if _EMAIL_OR_DOMAIN_PATTERN.fullmatch(normalized):
        return normalized
    return _domain(normalized) or normalized


def _has_legacy_suppression_rows(session) -> bool:
    normalized = func.lower(func.trim(func.coalesce(Suppression.email_or_domain, "")))
    row = session.execute(
        select(Suppression.id)
        .where((normalized.like("%://%")) | (normalized.like("%/%")) | (normalized.like("%:%")))
        .limit(1)
    ).scalar_one_or_none()
    return row is not None


def _build_domain_fallback_lookup(session) -> dict[str, Lead]:
    lookup: dict[str, Lead] = {}
    for lead in session.execute(
        select(Lead).where((Lead.website_domain.is_not(None)) | (Lead.website_url.is_not(None)))
    ).scalars():
        domain = _domain(lead.website_domain) or _domain(lead.website_url)
        if domain:
            lookup.setdefault(domain, lead)
    return lookup


def _find_existing_lead(
    session,
    *,
    place_id: str,
    website_url: str,
    domain_fallback_lookup: Mapping[str, Lead] | None = None,
    place_id_lookup_cache: dict[str, Lead | None] | None = None,
    website_domain_lookup_cache: dict[str, Lead | None] | None = None,
) -> Lead | None:
    normalized_place_id = (place_id or "").strip()
    if normalized_place_id:
        if place_id_lookup_cache is not None and normalized_place_id in place_id_lookup_cache:
            return place_id_lookup_cache[normalized_place_id]
        lead = session.execute(
            select(Lead).where(func.trim(func.coalesce(Lead.place_id, "")) == normalized_place_id)
        ).scalar_one_or_none()
        if place_id_lookup_cache is not None:
            place_id_lookup_cache[normalized_place_id] = lead
        if lead is not None:
            return lead

    target_domain = _domain(website_url)
    if not target_domain:
        return None

    if website_domain_lookup_cache is not None and target_domain in website_domain_lookup_cache:
        return website_domain_lookup_cache[target_domain]

    lead = session.execute(
        select(Lead).where(func.lower(func.trim(func.coalesce(Lead.website_domain, ""))) == target_domain)
    ).scalar_one_or_none()
    if lead is not None:
        if website_domain_lookup_cache is not None:
            website_domain_lookup_cache[target_domain] = lead
        return lead

    if domain_fallback_lookup is not None:
        lead = domain_fallback_lookup.get(target_domain)
        if website_domain_lookup_cache is not None:
            website_domain_lookup_cache[target_domain] = lead
        return lead

    for candidate in session.execute(
        select(Lead).where((Lead.website_domain.is_not(None)) | (Lead.website_url.is_not(None)))
    ).scalars():
        candidate_domain = _domain(candidate.website_domain) or _domain(candidate.website_url)
        if candidate_domain == target_domain:
            if website_domain_lookup_cache is not None:
                website_domain_lookup_cache[target_domain] = candidate
            return candidate
    if website_domain_lookup_cache is not None:
        website_domain_lookup_cache[target_domain] = None
    return None


def _suppression_values(session) -> set[str]:
    normalized_value = func.trim(func.coalesce(Suppression.email_or_domain, ""))
    if not _has_legacy_suppression_rows(session):
        return set(
            session.execute(
                select(func.lower(normalized_value)).where(
                    Suppression.email_or_domain.is_not(None),
                    normalized_value != "",
                )
            ).scalars()
        )

    values: set[str] = set()
    for raw_value in session.execute(
        select(Suppression.email_or_domain).where(Suppression.email_or_domain.is_not(None), normalized_value != "")
    ).scalars():
        normalized = _normalize_suppression_value(raw_value)
        if normalized:
            values.add(normalized)
    return values


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
        domain_fallback_lookup = _build_domain_fallback_lookup(session)
        place_id_lookup_cache: dict[str, Lead | None] = {}
        website_domain_lookup_cache: dict[str, Lead | None] = {}
        for item in discovered:
            lead_domain = _domain(item.website_url) or ""
            is_suppressed = lead_domain in suppression_values
            lead = _find_existing_lead(
                session,
                place_id=item.place_id,
                website_url=item.website_url,
                domain_fallback_lookup=domain_fallback_lookup,
                place_id_lookup_cache=place_id_lookup_cache,
                website_domain_lookup_cache=website_domain_lookup_cache,
            )
            if lead is None:
                lead = Lead(
                    name=item.name,
                    category=category,
                    source="google_places",
                    place_id=item.place_id,
                    website_url=item.website_url,
                    website_domain=lead_domain or None,
                    address=item.address,
                    phone=item.phone,
                    status="Suppressed" if is_suppressed else "Discovered",
                )
                session.add(lead)
                session.flush()
                if lead_domain:
                    domain_fallback_lookup.setdefault(lead_domain, lead)
                    website_domain_lookup_cache[lead_domain] = lead
                normalized_place_id = (item.place_id or "").strip()
                if normalized_place_id:
                    place_id_lookup_cache[normalized_place_id] = lead
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
                "website_domain": lead_domain or None,
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
                if lead_domain:
                    domain_fallback_lookup.setdefault(lead_domain, lead)
                    website_domain_lookup_cache[lead_domain] = lead
                normalized_place_id = (item.place_id or "").strip()
                if normalized_place_id:
                    place_id_lookup_cache[normalized_place_id] = lead
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
