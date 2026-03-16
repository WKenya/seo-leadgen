from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Lead, Suppression
from app.tasks.discover import (
    _build_domain_fallback_lookup,
    _find_existing_lead,
    _has_legacy_suppression_rows,
    _prefill_place_id_lookup_cache,
    _suppression_values,
)


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

    def test_find_existing_lead_fallback_matches_whitespace_padded_website_url(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Legacy URL Spaces",
            source="google_places",
            website_url="  https://legacy.example/home  ",
            website_domain=None,
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        found = _find_existing_lead(self.session, place_id="new-place", website_url="https://legacy.example/contact")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, lead.id)

    def test_find_existing_lead_matches_schemeless_website_url(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Legacy URL Schemeless",
            source="google_places",
            website_url="legacy.example/home",
            website_domain=None,
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        found = _find_existing_lead(self.session, place_id="new-place", website_url="legacy.example/contact")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, lead.id)

    def test_find_existing_lead_matches_website_url_with_port(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Legacy URL Port",
            source="google_places",
            website_url="https://legacy.example:443/home",
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

    def test_find_existing_lead_matches_legacy_domain_with_port(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Legacy Domain Port",
            source="google_places",
            website_url="https://legacy.example",
            website_domain="LeGaCy.ExAmPlE:443",
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        found = _find_existing_lead(self.session, place_id="new-place", website_url="https://legacy.example/contact")
        self.assertIsNotNone(found)
        self.assertEqual(found.id, lead.id)

    def test_build_domain_fallback_lookup_uses_hostname_for_legacy_rows(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Legacy URL Port",
            source="google_places",
            website_url="https://legacy.example:443/home",
            website_domain=None,
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        lookup = _build_domain_fallback_lookup(self.session)
        self.assertIn("legacy.example", lookup)
        self.assertEqual(lookup["legacy.example"].id, lead.id)

    def test_find_existing_lead_uses_prebuilt_domain_lookup(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Lookup Match",
            source="google_places",
            website_url="https://lookup.example/home",
            website_domain=None,
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        lookup = _build_domain_fallback_lookup(self.session)
        found = _find_existing_lead(
            self.session,
            place_id="new-place",
            website_url="https://lookup.example/contact",
            domain_fallback_lookup=lookup,
        )
        self.assertIsNotNone(found)
        self.assertEqual(found.id, lead.id)

    def test_find_existing_lead_caches_place_id_lookups(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Place Cache Match",
            source="google_places",
            place_id="place-123",
            website_url="https://acme.example",
            website_domain="acme.example",
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        place_id_lookup_cache: dict[str, Lead | None] = {}
        with patch.object(self.session, "execute", wraps=self.session.execute) as execute_mock:
            first = _find_existing_lead(
                self.session,
                place_id="place-123",
                website_url="https://acme.example",
                place_id_lookup_cache=place_id_lookup_cache,
            )
            call_count_after_first = execute_mock.call_count
            second = _find_existing_lead(
                self.session,
                place_id="place-123",
                website_url="https://acme.example",
                place_id_lookup_cache=place_id_lookup_cache,
            )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, lead.id)
        self.assertEqual(second.id, lead.id)
        self.assertEqual(execute_mock.call_count, call_count_after_first)

    def test_prefill_place_id_lookup_cache_includes_found_and_missing_ids(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Prefill Place Match",
            source="google_places",
            place_id="  place-123  ",
            website_url="https://acme.example",
            website_domain="acme.example",
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        cache = _prefill_place_id_lookup_cache(self.session, place_ids={"place-123", "missing-place"})
        self.assertIn("place-123", cache)
        self.assertIn("missing-place", cache)
        self.assertIsNotNone(cache["place-123"])
        self.assertEqual(cache["place-123"].id, lead.id)
        self.assertIsNone(cache["missing-place"])

    def test_prefill_place_id_lookup_cache_skips_ambiguous_duplicate_ids(self) -> None:
        first = Lead(
            id=uuid4(),
            name="Dup Place A",
            source="google_places",
            place_id="dup-place",
            website_url="https://a.example",
            website_domain="a.example",
            status="Discovered",
        )
        second = Lead(
            id=uuid4(),
            name="Dup Place B",
            source="google_places",
            place_id="  dup-place  ",
            website_url="https://b.example",
            website_domain="b.example",
            status="Discovered",
        )
        self.session.add_all([first, second])
        self.session.commit()

        cache = _prefill_place_id_lookup_cache(self.session, place_ids={"dup-place"})
        self.assertNotIn("dup-place", cache)

    def test_find_existing_lead_caches_domain_lookups(self) -> None:
        lead = Lead(
            id=uuid4(),
            name="Domain Cache Match",
            source="google_places",
            website_url="https://acme.example",
            website_domain="acme.example",
            status="Discovered",
        )
        self.session.add(lead)
        self.session.commit()

        website_domain_lookup_cache: dict[str, Lead | None] = {}
        with patch.object(self.session, "execute", wraps=self.session.execute) as execute_mock:
            first = _find_existing_lead(
                self.session,
                place_id="",
                website_url="https://acme.example",
                website_domain_lookup_cache=website_domain_lookup_cache,
            )
            call_count_after_first = execute_mock.call_count
            second = _find_existing_lead(
                self.session,
                place_id="",
                website_url="https://acme.example",
                website_domain_lookup_cache=website_domain_lookup_cache,
            )

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.id, lead.id)
        self.assertEqual(second.id, lead.id)
        self.assertEqual(execute_mock.call_count, call_count_after_first)

    def test_suppression_values_normalizes_legacy_whitespace_and_case(self) -> None:
        self.session.add(Suppression(email_or_domain="  Acme.Example  ", reason="opt_out"))
        self.session.commit()

        values = _suppression_values(self.session)
        self.assertIn("acme.example", values)

    def test_suppression_values_normalizes_legacy_url_rows(self) -> None:
        self.session.add(Suppression(email_or_domain="  https://Acme.Example/path  ", reason="opt_out"))
        self.session.commit()

        values = _suppression_values(self.session)
        self.assertIn("acme.example", values)

    def test_suppression_values_normalizes_legacy_url_rows_with_userinfo(self) -> None:
        self.session.add(Suppression(email_or_domain="https://user@Acme.Example/path", reason="opt_out"))
        self.session.commit()

        values = _suppression_values(self.session)
        self.assertIn("acme.example", values)

    def test_suppression_values_handles_mixed_canonical_and_legacy_rows(self) -> None:
        self.session.add(Suppression(email_or_domain="owner@acme.example", reason="opt_out"))
        self.session.add(Suppression(email_or_domain="https://Acme.Example/path", reason="opt_out"))
        self.session.commit()

        values = _suppression_values(self.session)
        self.assertIn("owner@acme.example", values)
        self.assertIn("acme.example", values)

    def test_suppression_values_ignores_blank_rows(self) -> None:
        self.session.add(Suppression(email_or_domain="   ", reason="opt_out"))
        self.session.commit()

        values = _suppression_values(self.session)
        self.assertEqual(values, set())

    def test_has_legacy_suppression_rows_false_for_canonical_values(self) -> None:
        self.session.add(Suppression(email_or_domain="owner@acme.example", reason="opt_out"))
        self.session.add(Suppression(email_or_domain="acme.example", reason="opt_out"))
        self.session.commit()

        self.assertFalse(_has_legacy_suppression_rows(self.session))

    def test_has_legacy_suppression_rows_true_for_url_values(self) -> None:
        self.session.add(Suppression(email_or_domain="https://acme.example/path", reason="opt_out"))
        self.session.commit()

        self.assertTrue(_has_legacy_suppression_rows(self.session))


if __name__ == "__main__":
    unittest.main()
