from __future__ import annotations

import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Lead, Suppression
from app.tasks.discover import _find_existing_lead, _suppression_values


class DiscoverDomainLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Lead.__table__.create(self.engine)
        Suppression.__table__.create(self.engine)
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

    def test_find_existing_lead_by_place_id_with_legacy_whitespace(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Acme HVAC",
            source="google_places",
            place_id="  place-123  ",
            website_url="",
            website_domain=None,
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        found = _find_existing_lead(self.session, place_id="place-123", website_url="")
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

    def test_find_existing_lead_does_not_fallback_match_when_target_domain_missing(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Legacy Missing Domain",
            source="google_places",
            website_url="",
            website_domain=None,
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        found = _find_existing_lead(self.session, place_id="new-place", website_url="")
        self.assertIsNone(found)

    def test_find_existing_lead_matches_legacy_mixed_case_whitespace_domain(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Legacy HVAC",
            source="google_places",
            website_url="https://legacy.example",
            website_domain="  LeGaCy.ExAmPlE  ",
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        found = _find_existing_lead(self.session, place_id="new-place", website_url="https://legacy.example/contact")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, lead.id)

    def test_suppression_values_normalizes_legacy_whitespace_and_case(self) -> None:
        self.session.add(Suppression(email_or_domain="  Acme.Example  ", reason="opt_out"))
        self.session.commit()

        values = _suppression_values(self.session)
        self.assertIn("acme.example", values)


if __name__ == "__main__":
    unittest.main()
