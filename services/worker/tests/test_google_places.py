from __future__ import annotations

import sys
from pathlib import Path
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.discovery.google_places import normalize_website_url  # noqa: E402


class GooglePlacesTests(unittest.TestCase):
    def test_normalize_website_url_strips_tracking_and_fragment(self) -> None:
        url = "Example.com/?utm_source=x&fbclid=abc&keep=1#frag"
        self.assertEqual(normalize_website_url(url), "https://example.com?keep=1")

    def test_normalize_website_url_keeps_path_and_normalizes_scheme_case(self) -> None:
        url = "HTTP://WWW.Example.com/contact/?mc_eid=1"
        self.assertEqual(normalize_website_url(url), "http://www.example.com/contact/")

    def test_normalize_website_url_handles_empty(self) -> None:
        self.assertIsNone(normalize_website_url(""))
        self.assertIsNone(normalize_website_url(None))


if __name__ == "__main__":
    unittest.main()

