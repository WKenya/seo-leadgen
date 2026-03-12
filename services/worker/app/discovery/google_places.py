from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

TRACKING_QUERY_KEYS = {"gclid", "fbclid", "mc_cid", "mc_eid"}


@dataclass(slots=True)
class PlaceLead:
    name: str
    place_id: str
    address: str | None
    phone: str | None
    website_url: str
    raw: dict[str, Any]


def normalize_website_url(url: str | None) -> str | None:
    if not url:
        return None
    value = url.strip()
    if not value:
        return None
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlparse(value)
    if not parsed.netloc:
        return None
    scheme = parsed.scheme.lower() or "https"
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return None
    host = f"[{hostname}]" if ":" in hostname else hostname
    try:
        port = parsed.port
    except ValueError:
        return None
    is_default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    netloc = host if (port is None or is_default_port) else f"{host}:{port}"
    query_items = []
    for key, val in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower().startswith("utm_"):
            continue
        if key.lower() in TRACKING_QUERY_KEYS:
            continue
        query_items.append((key, val))
    path = parsed.path or "/"
    if path == "/":
        path = ""
    clean = parsed._replace(
        scheme=scheme,
        netloc=netloc,
        path=path,
        params="",
        query=urlencode(query_items, doseq=True),
        fragment="",
    )
    return urlunparse(clean)


class GooglePlacesClient:
    base_url = "https://maps.googleapis.com/maps/api/place"
    geocode_base_url = "https://maps.googleapis.com/maps/api/geocode"

    def __init__(self, api_key: str, timeout_seconds: float = 30.0) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        merged = dict(params)
        merged["key"] = self.api_key
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(f"{self.base_url}/{path}", params=merged)
            response.raise_for_status()
            payload = response.json()
        status = payload.get("status")
        if status not in {"OK", "ZERO_RESULTS"}:
            raise RuntimeError(f"google_places_error: {status} {payload.get('error_message', '')}".strip())
        return payload

    def _get_geocode(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        merged = dict(params)
        merged["key"] = self.api_key
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(f"{self.geocode_base_url}/{path}", params=merged)
            response.raise_for_status()
            payload = response.json()
        status = payload.get("status")
        if status not in {"OK", "ZERO_RESULTS"}:
            raise RuntimeError(f"google_geocode_error: {status} {payload.get('error_message', '')}".strip())
        return payload

    def _wait_for_page_token(self) -> None:
        # Google Places pagination token often needs a short warm-up delay.
        time.sleep(2.0)

    def text_search(self, *, city: str, category: str, page_token: str | None = None) -> dict[str, Any]:
        query = f"{category} in {city}"
        params: dict[str, Any] = {"query": query, "region": "us"}
        if page_token:
            params = {"pagetoken": page_token}
        return self._get("textsearch/json", params)

    def geocode_city(self, city: str) -> tuple[float, float] | None:
        payload = self._get_geocode("json", {"address": city, "region": "us"})
        results = payload.get("results") or []
        if not results:
            return None
        location = (((results[0] or {}).get("geometry") or {}).get("location") or {})
        lat = location.get("lat")
        lng = location.get("lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            return float(lat), float(lng)
        return None

    def nearby_search(
        self,
        *,
        lat: float,
        lng: float,
        radius_meters: int,
        category: str,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any]
        if page_token:
            params = {"pagetoken": page_token}
        else:
            params = {
                "location": f"{lat},{lng}",
                "radius": max(1, min(int(radius_meters), 50000)),
                "keyword": category,
            }
        return self._get("nearbysearch/json", params)

    def _collect_paginated(self, fetch_page, *, limit: int) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_page_token: str | None = None
        seen_place_ids: set[str] = set()
        while len(results) < limit:
            if next_page_token:
                self._wait_for_page_token()
            payload = fetch_page(next_page_token)
            for row in payload.get("results", []):
                place_id = row.get("place_id")
                if place_id and place_id in seen_place_ids:
                    continue
                if place_id:
                    seen_place_ids.add(place_id)
                results.append(row)
                if len(results) >= limit:
                    break
            next_page_token = payload.get("next_page_token")
            if not next_page_token:
                break
        return results[:limit]

    def text_search_paginated(self, *, city: str, category: str, limit: int) -> list[dict[str, Any]]:
        return self._collect_paginated(
            lambda page_token: self.text_search(city=city, category=category, page_token=page_token),
            limit=limit,
        )

    def nearby_search_paginated(
        self,
        *,
        city: str,
        category: str,
        radius_meters: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        point = self.geocode_city(city)
        if point is None:
            return []
        lat, lng = point
        return self._collect_paginated(
            lambda page_token: self.nearby_search(
                lat=lat,
                lng=lng,
                radius_meters=radius_meters,
                category=category,
                page_token=page_token,
            ),
            limit=limit,
        )

    def place_details(self, place_id: str) -> dict[str, Any]:
        payload = self._get(
            "details/json",
            {
                "place_id": place_id,
                "fields": ",".join(
                    [
                        "name",
                        "formatted_address",
                        "website",
                        "formatted_phone_number",
                        "international_phone_number",
                    ]
                ),
            },
        )
        return payload.get("result", {})

    def discover_leads(
        self,
        *,
        city: str,
        category: str,
        limit: int = 20,
        radius_meters: int | None = None,
    ) -> list[PlaceLead]:
        results = []
        if radius_meters and radius_meters > 0:
            results = self.nearby_search_paginated(
                city=city,
                category=category,
                radius_meters=radius_meters,
                limit=limit,
            )
        if not results:
            results = self.text_search_paginated(city=city, category=category, limit=limit)
        leads: list[PlaceLead] = []
        for row in results[:limit]:
            place_id = row.get("place_id")
            if not place_id:
                continue
            detail = self.place_details(place_id)
            website_url = normalize_website_url(detail.get("website"))
            if not website_url:
                continue
            leads.append(
                PlaceLead(
                    name=detail.get("name") or row.get("name") or "Unknown",
                    place_id=place_id,
                    address=detail.get("formatted_address") or row.get("formatted_address"),
                    phone=detail.get("formatted_phone_number") or detail.get("international_phone_number"),
                    website_url=website_url,
                    raw={"search": row, "details": detail},
                )
            )
        return leads
