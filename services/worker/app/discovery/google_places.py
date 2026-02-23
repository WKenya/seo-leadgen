from __future__ import annotations

from dataclasses import dataclass
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
    netloc = parsed.netloc.lower()
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

    def text_search(self, *, city: str, category: str) -> list[dict[str, Any]]:
        query = f"{category} in {city}"
        payload = self._get("textsearch/json", {"query": query, "region": "us"})
        return payload.get("results", [])

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

    def discover_leads(self, *, city: str, category: str, limit: int = 20) -> list[PlaceLead]:
        results = self.text_search(city=city, category=category)
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

