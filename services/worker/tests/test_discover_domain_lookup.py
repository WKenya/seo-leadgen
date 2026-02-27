from __future__ import annotations

import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Lead
from app.tasks.discover import _find_existing_lead


class DiscoverDomainLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Lead.__table__.create(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.session = self.SessionLocal()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_find_existing_lead_by_website_domain(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Acme HVAC",
            source="google_places",
            website_url="https://acme.example",
            website_domain="acme.example",
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        found = _find_existing_lead(self.session, place_id="new-place", website_url="https://acme.example/contact")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, lead.id)

    def test_find_existing_lead_falls_back_when_website_domain_missing(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Legacy HVAC",
            source="google_places",
            website_url="https://legacy.example/home",
            website_domain=None,
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        found = _find_existing_lead(self.session, place_id="new-place", website_url="https://legacy.example/contact")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, lead.id)


if __name__ == "__main__":
    unittest.main()
