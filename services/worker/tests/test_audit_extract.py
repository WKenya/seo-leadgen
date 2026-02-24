from __future__ import annotations

import sys
from pathlib import Path
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.audit.extract import (  # noqa: E402
    choose_preferred_email,
    extract_basic_seo_signals,
    extract_emails,
    extract_links,
    find_contact_signals,
    is_internal_url,
    normalize_link,
)


class AuditExtractTests(unittest.TestCase):
    def test_extract_emails_dedupes(self) -> None:
        text = "Contact a@b.com and a@b.com or help@example.org"
        self.assertEqual(extract_emails(text), ["a@b.com", "help@example.org"])

    def test_extract_links_reads_anchor_hrefs(self) -> None:
        html = '<a href="/contact">Contact</a><a href="https://x.test">X</a>'
        self.assertEqual(extract_links(html), ["/contact", "https://x.test"])

    def test_normalize_link_skips_non_http_targets(self) -> None:
        self.assertIsNone(normalize_link("https://example.com", "mailto:test@example.com"))
        self.assertIsNone(normalize_link("https://example.com", "#section"))
        self.assertEqual(normalize_link("https://example.com", "/a"), "https://example.com/a")

    def test_internal_url_classification(self) -> None:
        self.assertTrue(is_internal_url("https://example.com", "https://example.com/about"))
        self.assertFalse(is_internal_url("https://example.com", "https://other.com/about"))

    def test_find_contact_signals_detects_contact_page_mailto_tel(self) -> None:
        html = """
        <html><body>
          <a href="/contact">Contact Us</a>
          <a href="mailto:team@example.com">Email</a>
          <a href="tel:+12165551212">Call</a>
        </body></html>
        """
        links = extract_links(html)
        signals = find_contact_signals(html, "https://example.com", links)
        self.assertTrue(signals["has_contact_page"])
        self.assertEqual(signals["contact_page_url"], "https://example.com/contact")
        self.assertTrue(signals["has_mailto"])
        self.assertTrue(signals["has_tel"])
        self.assertIn("team@example.com", signals["emails_found"])

    def test_choose_preferred_email_prefers_non_role_address(self) -> None:
        emails = ["info@example.com", "owner@example.com", "support@example.com"]
        self.assertEqual(choose_preferred_email(emails), "owner@example.com")
        self.assertEqual(choose_preferred_email(["info@example.com"]), "info@example.com")
        self.assertIsNone(choose_preferred_email([]))

    def test_extract_basic_seo_signals(self) -> None:
        html = """
        <html>
          <head>
            <title>Acme HVAC Cleveland</title>
            <meta name="description" content="Fast HVAC service" />
            <meta name="robots" content="index,follow" />
            <link rel="canonical" href="/home" />
          </head>
        </html>
        """
        seo = extract_basic_seo_signals(html, "https://example.com")
        self.assertTrue(seo["title_present"])
        self.assertTrue(seo["meta_description_present"])
        self.assertTrue(seo["canonical_present"])
        self.assertEqual(seo["canonical_url"], "https://example.com/home")
        self.assertFalse(seo["robots_noindex"])


if __name__ == "__main__":
    unittest.main()
