from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.discovery.google_places import GooglePlacesClient, normalize_website_url  # noqa: E402


class GooglePlacesTests(unittest.TestCase):
    def test_normalize_website_url_strips_tracking_and_fragment(self) -> None:
        url = "Example.com/?utm_source=x&fbclid=abc&keep=1#frag"
        self.assertEqual(normalize_website_url(url), "https://example.com?keep=1")

    def test_normalize_website_url_keeps_path_and_normalizes_scheme_case(self) -> None:
        url = "HTTP://WWW.Example.com/contact/?mc_eid=1"
        self.assertEqual(normalize_website_url(url), "http://www.example.com/contact/")

    def test_normalize_website_url_drops_default_ports(self) -> None:
        self.assertEqual(normalize_website_url("https://Example.com:443/path"), "https://example.com/path")
        self.assertEqual(normalize_website_url("http://Example.com:80/path"), "http://example.com/path")

    def test_normalize_website_url_keeps_non_default_port(self) -> None:
        self.assertEqual(normalize_website_url("https://Example.com:8443/path"), "https://example.com:8443/path")

    def test_normalize_website_url_handles_empty(self) -> None:
        self.assertIsNone(normalize_website_url(""))
        self.assertIsNone(normalize_website_url(None))

    def test_collect_paginated_dedupes_place_ids(self) -> None:
        client = GooglePlacesClient(api_key="x")
        client._wait_for_page_token = lambda: None  # type: ignore[method-assign]
        pages = [
            {"results": [{"place_id": "1"}, {"place_id": "2"}], "next_page_token": "n1"},
            {"results": [{"place_id": "2"}, {"place_id": "3"}]},
        ]

        def fetch(page_token):
            if page_token is None:
                return pages[0]
            return pages[1]

        rows = client._collect_paginated(fetch, limit=10)
        self.assertEqual([row["place_id"] for row in rows], ["1", "2", "3"])

    def test_discover_leads_falls_back_to_text_search_when_nearby_empty(self) -> None:
        class FakeClient(GooglePlacesClient):
            def __init__(self) -> None:
                super().__init__(api_key="x")
                self.called: list[str] = []

            def nearby_search_paginated(self, *, city, category, radius_meters, limit):  # type: ignore[override]
                self.called.append("nearby")
                return []

            def text_search_paginated(self, *, city, category, limit):  # type: ignore[override]
                self.called.append("text")
                return [{"place_id": "p1", "name": "Acme", "formatted_address": "123 Main"}]

            def place_details(self, place_id):  # type: ignore[override]
                return {"name": "Acme", "website": "acme.example", "formatted_phone_number": "216-555-0100"}

        client = FakeClient()
        leads = client.discover_leads(city="Cleveland, OH", category="HVAC", limit=5, radius_meters=15000)
        self.assertEqual(client.called, ["nearby", "text"])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0].website_url, "https://acme.example")

    def test_get_retries_retryable_http_status_errors(self) -> None:
        class FakeClient(GooglePlacesClient):
            def __init__(self) -> None:
                super().__init__(api_key="x")
                self.calls = 0

            def _fetch_json(self, *, client, base_url, path, params):  # type: ignore[override]
                del client, base_url, path, params
                self.calls += 1
                if self.calls < 3:
                    request = httpx.Request("GET", "https://example.test")
                    response = httpx.Response(503, request=request)
                    raise httpx.HTTPStatusError("temporary", request=request, response=response)
                return {"status": "OK", "results": []}

        client = FakeClient()
        with patch("app.discovery.google_places.time.sleep", return_value=None):
            payload = client._get("textsearch/json", {"query": "hvac in cleveland"})

        self.assertEqual(payload.get("status"), "OK")
        self.assertEqual(client.calls, 3)


if __name__ == "__main__":
    unittest.main()
