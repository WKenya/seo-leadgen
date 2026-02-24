from __future__ import annotations

import sys
from pathlib import Path
import unittest
import uuid
from types import SimpleNamespace

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.integrations.notion_leads import REQUIRED_NOTION_PROPERTIES, lead_page_properties  # noqa: E402

class NotionLeadsTests(unittest.TestCase):
    def test_lead_page_properties_contains_required_keys(self) -> None:
        lead = SimpleNamespace(
            id=uuid.uuid4(),
            name="Acme HVAC",
            category="HVAC",
            source="google_places",
            website_url="https://acme.example",
            status="Draft Ready",
            email="owner@acme.example",
            phone=None,
            address=None,
        )
        audit = SimpleNamespace(
            id=uuid.uuid4(),
            lead_id=lead.id,
            cert_error=None,
            crawl_summary={"broken_links_count": 2},
            contact_signals={"has_contact_page": False},
        )
        draft = SimpleNamespace(
            id=uuid.uuid4(),
            lead_id=lead.id,
            audit_id=audit.id,
            subject="Quick fixes",
            body_text="Hello",
            gmail_draft_url="https://mail.google.com/",
        )

        props = lead_page_properties(lead=lead, audit=audit, draft=draft)
        self.assertTrue(REQUIRED_NOTION_PROPERTIES.issubset(set(props.keys())))
        self.assertEqual(props["Website"]["url"], "https://acme.example")
        self.assertEqual(props["Gmail Draft Link"]["url"], "https://mail.google.com/")


if __name__ == "__main__":
    unittest.main()
