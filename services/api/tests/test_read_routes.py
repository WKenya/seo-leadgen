from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from uuid import uuid4

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

HAS_API_DEPS = True
IMPORT_ERROR = ""
try:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import StaticPool
except Exception as exc:  # noqa: BLE001
    HAS_API_DEPS = False
    IMPORT_ERROR = str(exc)

if HAS_API_DEPS:
    from sqlite_test_shims import install_sqlite_shims

    install_sqlite_shims()


class ReadRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        if not HAS_API_DEPS:
            self.skipTest(f"api test deps missing: {IMPORT_ERROR}")

        from app.db import get_db
        from app.main import create_app
        from app.models import Base
        from app.settings import get_settings

        self._get_db = get_db
        self._get_settings = get_settings
        self._env_backup = {
            "WEBHOOK_SHARED_SECRET": os.environ.get("WEBHOOK_SHARED_SECRET"),
            "WEBHOOK_SIGNATURE_SECRET": os.environ.get("WEBHOOK_SIGNATURE_SECRET"),
            "WEBHOOK_SIGNATURE_TOLERANCE_SECONDS": os.environ.get("WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"),
            "POSTMARK_WEBHOOK_TOKEN": os.environ.get("POSTMARK_WEBHOOK_TOKEN"),
            "MAILGUN_WEBHOOK_SIGNING_KEY": os.environ.get("MAILGUN_WEBHOOK_SIGNING_KEY"),
        }
        os.environ.setdefault("WEBHOOK_SHARED_SECRET", "test_shared_secret")
        os.environ.setdefault("WEBHOOK_SIGNATURE_SECRET", "")
        os.environ.setdefault("WEBHOOK_SIGNATURE_TOLERANCE_SECONDS", "300")
        os.environ.setdefault("POSTMARK_WEBHOOK_TOKEN", "")
        os.environ.setdefault("MAILGUN_WEBHOOK_SIGNING_KEY", "")
        self._get_settings.cache_clear()

        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db: Session = self.SessionLocal()

        self.app = create_app()

        def _override_get_db():
            yield self.db

        self.app.dependency_overrides[self._get_db] = _override_get_db
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        if not HAS_API_DEPS:
            return
        self.client.close()
        self.app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._get_settings.cache_clear()

    def _seed_lead_bundle(self):
        from app.models import Audit, EmailDraft, Issue, Lead, OutreachEvent, Suppression

        now = datetime.now(timezone.utc)
        lead1 = Lead(
            id=uuid4(),
            name="Acme HVAC",
            category="HVAC",
            source="google_places",
            website_url="https://acme.example",
            email="owner@acme.example",
            status="Draft Ready",
        )
        lead2 = Lead(
            id=uuid4(),
            name="Bravo Dental",
            category="Dentist",
            source="google_places",
            website_url="https://bravo.example",
            email="info@bravo.example",
            status="Suppressed",
        )
        audit = Audit(
            id=uuid4(),
            lead_id=lead1.id,
            final_url=lead1.website_url,
            started_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=20),
        )
        issue1 = Issue(
            id=uuid4(),
            audit_id=audit.id,
            kind="seo",
            severity=2,
            title="Missing meta description",
            details={"url": "https://acme.example"},
        )
        issue2 = Issue(
            id=uuid4(),
            audit_id=audit.id,
            kind="broken_link",
            severity=4,
            title="Broken link: /pricing",
            details={"url": "https://acme.example/pricing", "status": 404},
        )
        draft_old = EmailDraft(
            id=uuid4(),
            lead_id=lead1.id,
            audit_id=audit.id,
            subject="Old",
            body_text="old",
            created_at=now - timedelta(minutes=15),
        )
        draft_new = EmailDraft(
            id=uuid4(),
            lead_id=lead1.id,
            audit_id=audit.id,
            subject="New",
            body_text="new",
            created_at=now - timedelta(minutes=5),
        )
        event_old = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="approved",
            provider="sendgrid",
            payload={"draft_id": str(draft_old.id), "provider": "sendgrid", "provider_event_id": "sg-1"},
            created_at=now - timedelta(minutes=10),
        )
        event_new = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="sent",
            provider="mailgun",
            payload={"draft_id": str(draft_new.id), "provider": "mailgun", "provider_event_id": "mg-1"},
            created_at=now - timedelta(minutes=1),
        )
        event_other = OutreachEvent(
            id=uuid4(),
            lead_id=lead2.id,
            type="opt_out",
            provider="postmark",
            payload={"provider": "postmark", "provider_event_id": "pm-1"},
            created_at=now - timedelta(minutes=2),
        )
        suppression1 = Suppression(email_or_domain="owner@acme.example", reason="opt_out", created_at=now)
        suppression2 = Suppression(email_or_domain="bravo.example", reason="bounce", created_at=now - timedelta(days=1))

        self.db.add_all(
            [
                lead1,
                lead2,
                audit,
                issue1,
                issue2,
                draft_old,
                draft_new,
                event_old,
                event_new,
                event_other,
                suppression1,
                suppression2,
            ]
        )
        self.db.commit()
        return {
            "lead1": lead1,
            "lead2": lead2,
            "audit": audit,
            "issues": [issue1, issue2],
            "draft_old": draft_old,
            "draft_new": draft_new,
        }

    def test_get_audit_and_list_issues_orders_by_severity_then_title(self) -> None:
        seeded = self._seed_lead_bundle()
        audit = seeded["audit"]

        audit_resp = self.client.get(f"/audits/{audit.id}")
        self.assertEqual(audit_resp.status_code, 200, audit_resp.text)
        self.assertEqual(audit_resp.json()["id"], str(audit.id))

        issues_resp = self.client.get(f"/audits/{audit.id}/issues")
        self.assertEqual(issues_resp.status_code, 200, issues_resp.text)
        items = issues_resp.json()["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual([item["severity"] for item in items], [4, 2])

    def test_get_audit_404_when_missing(self) -> None:
        response = self.client.get(f"/audits/{uuid4()}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "audit not found")

    def test_list_drafts_and_get_draft_support_filters(self) -> None:
        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]
        draft_new = seeded["draft_new"]
        draft_old = seeded["draft_old"]

        response = self.client.get("/drafts", params={"lead_id": str(lead1.id), "limit": 1, "offset": 1})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sort"], "desc")
        self.assertEqual(body["limit"], 1)
        self.assertEqual(body["offset"], 1)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["total"], 2)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_offset"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["id"], str(draft_old.id))

        asc_response = self.client.get("/drafts", params={"lead_id": str(lead1.id), "limit": 1, "offset": 0, "sort": "asc"})
        self.assertEqual(asc_response.status_code, 200, asc_response.text)
        asc_body = asc_response.json()
        self.assertEqual(asc_body["sort"], "asc")
        self.assertEqual(asc_body["items"][0]["id"], str(draft_old.id))

        get_resp = self.client.get(f"/drafts/{draft_new.id}")
        self.assertEqual(get_resp.status_code, 200, get_resp.text)
        self.assertEqual(get_resp.json()["id"], str(draft_new.id))

    def test_list_events_and_lead_events_filter_by_type(self) -> None:
        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]

        response = self.client.get("/events", params={"event_type": "sent", "limit": 10, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sort"], "desc")
        self.assertEqual(body["limit"], 10)
        self.assertEqual(body["offset"], 0)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["total"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_offset"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["type"], "sent")

        lead_resp = self.client.get(f"/leads/{lead1.id}/events", params={"event_type": "approved", "limit": 10, "offset": 0})
        self.assertEqual(lead_resp.status_code, 200, lead_resp.text)
        lead_items = lead_resp.json()["items"]
        self.assertEqual(lead_resp.json()["sort"], "desc")
        self.assertEqual(len(lead_items), 1)
        self.assertEqual(lead_items[0]["type"], "approved")

    def test_list_events_and_lead_events_filter_by_provider(self) -> None:
        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]

        response = self.client.get("/events", params={"provider": "postmark", "limit": 10, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sort"], "desc")
        self.assertEqual(body["limit"], 10)
        self.assertEqual(body["offset"], 0)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["total"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_offset"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["payload"]["provider"], "postmark")
        self.assertEqual(body["items"][0]["provider"], "postmark")
        self.assertEqual(body["items"][0]["provider_event_id"], "pm-1")

        lead_resp = self.client.get(f"/leads/{lead1.id}/events", params={"provider": "mailgun", "limit": 10, "offset": 0})
        self.assertEqual(lead_resp.status_code, 200, lead_resp.text)
        lead_items = lead_resp.json()["items"]
        self.assertEqual(lead_resp.json()["sort"], "desc")
        self.assertEqual(len(lead_items), 1)
        self.assertEqual(lead_items[0]["type"], "sent")
        self.assertEqual(lead_items[0]["payload"]["provider"], "mailgun")
        self.assertEqual(lead_items[0]["provider"], "mailgun")
        self.assertEqual(lead_items[0]["provider_event_id"], "mg-1")

        mixed_case_resp = self.client.get("/events", params={"provider": "MaIlGuN", "limit": 10, "offset": 0})
        self.assertEqual(mixed_case_resp.status_code, 200, mixed_case_resp.text)
        mixed_items = mixed_case_resp.json()["items"]
        self.assertEqual(len(mixed_items), 1)
        self.assertEqual(mixed_items[0]["provider"], "mailgun")

    def test_list_events_provider_filter_matches_mixed_case_stored_provider(self) -> None:
        from app.models import OutreachEvent

        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]
        legacy_event = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="manual",
            provider="MaIlGuN",
            payload={"provider": "mailgun", "provider_event_id": "mg-legacy-1"},
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(legacy_event)
        self.db.commit()

        response = self.client.get("/events", params={"provider": "mailgun", "limit": 20, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        self.assertTrue(any(item["id"] == str(legacy_event.id) for item in items))

        lead_response = self.client.get(f"/leads/{lead1.id}/events", params={"provider": "mailgun", "limit": 20, "offset": 0})
        self.assertEqual(lead_response.status_code, 200, lead_response.text)
        lead_items = lead_response.json()["items"]
        self.assertTrue(any(item["id"] == str(legacy_event.id) for item in lead_items))

    def test_list_events_provider_filter_matches_whitespace_padded_stored_provider(self) -> None:
        from app.models import OutreachEvent

        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]
        legacy_event = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="manual",
            provider="  MaIlGuN  ",
            payload={"provider": "mailgun", "provider_event_id": "mg-legacy-space-1"},
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(legacy_event)
        self.db.commit()

        response = self.client.get("/events", params={"provider": "mailgun", "limit": 20, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        matching = [item for item in items if item["id"] == str(legacy_event.id)]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["provider"], "mailgun")

    def test_list_events_normalizes_provider_from_payload_when_column_missing(self) -> None:
        from app.models import OutreachEvent

        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]
        legacy_event = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="manual",
            provider=None,
            payload={"provider": "  SeNdGrId  ", "provider_event_id": "sg-payload-1"},
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(legacy_event)
        self.db.commit()

        response = self.client.get("/events", params={"limit": 20, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        matching = [item for item in items if item["id"] == str(legacy_event.id)]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["provider"], "sendgrid")

    def test_list_events_trims_external_and_provider_event_fields(self) -> None:
        from app.models import OutreachEvent

        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]
        legacy_event = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="manual",
            external_id="  evt-legacy-1  ",
            provider=None,
            payload={
                "provider": "  SeNdGrId  ",
                "provider_event_id": "  sg-legacy-1  ",
                "provider_event_name": "  Delivered  ",
                "provider_event_at": "  2026-03-09T10:00:00Z  ",
            },
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(legacy_event)
        self.db.commit()

        response = self.client.get("/events", params={"limit": 20, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        matching = [item for item in items if item["id"] == str(legacy_event.id)]
        self.assertEqual(len(matching), 1)
        item = matching[0]
        self.assertEqual(item["external_id"], "evt-legacy-1")
        self.assertEqual(item["provider"], "sendgrid")
        self.assertEqual(item["provider_event_id"], "sg-legacy-1")
        self.assertEqual(item["provider_event_name"], "Delivered")
        self.assertEqual(item["provider_event_at"], "2026-03-09T10:00:00Z")

    def test_list_events_blank_external_and_provider_event_fields_normalize_to_none(self) -> None:
        from app.models import OutreachEvent

        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]
        legacy_event = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="manual",
            external_id="   ",
            provider=None,
            payload={
                "provider": "  mailgun  ",
                "provider_event_id": "   ",
                "provider_event_name": "   ",
                "provider_event_at": "   ",
            },
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(legacy_event)
        self.db.commit()

        response = self.client.get("/events", params={"limit": 20, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        matching = [item for item in items if item["id"] == str(legacy_event.id)]
        self.assertEqual(len(matching), 1)
        item = matching[0]
        self.assertIsNone(item["external_id"])
        self.assertEqual(item["provider"], "mailgun")
        self.assertIsNone(item["provider_event_id"])
        self.assertIsNone(item["provider_event_name"])
        self.assertIsNone(item["provider_event_at"])

    def test_list_events_ignores_blank_provider_and_event_type_filters(self) -> None:
        self._seed_lead_bundle()

        response = self.client.get("/events", params={"provider": "   ", "event_type": "   ", "limit": 10, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 3)
        self.assertEqual(body["count"], 3)

    def test_list_events_event_type_filter_matches_mixed_case_stored_type(self) -> None:
        from app.models import OutreachEvent

        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]
        legacy_event = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="SeNt",
            provider="mailgun",
            payload={"provider": "mailgun", "provider_event_id": "mg-legacy-sent-1"},
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(legacy_event)
        self.db.commit()

        response = self.client.get("/events", params={"event_type": "sent", "limit": 20, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        matching = [item for item in items if item["id"] == str(legacy_event.id)]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["type"], "sent")

        lead_response = self.client.get(f"/leads/{lead1.id}/events", params={"event_type": "sent", "limit": 20, "offset": 0})
        self.assertEqual(lead_response.status_code, 200, lead_response.text)
        lead_items = lead_response.json()["items"]
        lead_matching = [item for item in lead_items if item["id"] == str(legacy_event.id)]
        self.assertEqual(len(lead_matching), 1)
        self.assertEqual(lead_matching[0]["type"], "sent")

    def test_list_events_event_type_filter_matches_whitespace_padded_stored_type(self) -> None:
        from app.models import OutreachEvent

        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]
        legacy_event = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="  SeNt  ",
            provider="mailgun",
            payload={"provider": "mailgun", "provider_event_id": "mg-legacy-sent-space-1"},
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(legacy_event)
        self.db.commit()

        response = self.client.get("/events", params={"event_type": "sent", "limit": 20, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        items = response.json()["items"]
        matching = [item for item in items if item["id"] == str(legacy_event.id)]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["type"], "sent")

    def test_list_events_and_lead_events_support_offset(self) -> None:
        seeded = self._seed_lead_bundle()
        lead1 = seeded["lead1"]

        response = self.client.get("/events", params={"limit": 1, "offset": 1})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sort"], "desc")
        self.assertEqual(body["limit"], 1)
        self.assertEqual(body["offset"], 1)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["total"], 3)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["next_offset"], 2)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["type"], "opt_out")

        lead_resp = self.client.get(f"/leads/{lead1.id}/events", params={"limit": 1, "offset": 1})
        self.assertEqual(lead_resp.status_code, 200, lead_resp.text)
        lead_body = lead_resp.json()
        self.assertEqual(lead_body["sort"], "desc")
        self.assertEqual(lead_body["limit"], 1)
        self.assertEqual(lead_body["offset"], 1)
        self.assertEqual(lead_body["count"], 1)
        self.assertEqual(lead_body["total"], 2)
        self.assertFalse(lead_body["has_more"])
        self.assertIsNone(lead_body["next_offset"])
        self.assertEqual(len(lead_body["items"]), 1)
        self.assertEqual(lead_body["items"][0]["type"], "approved")

        asc_response = self.client.get("/events", params={"limit": 1, "offset": 0, "sort": "asc"})
        self.assertEqual(asc_response.status_code, 200, asc_response.text)
        asc_body = asc_response.json()
        self.assertEqual(asc_body["sort"], "asc")
        self.assertEqual(asc_body["items"][0]["type"], "approved")

    def test_list_suppression_supports_q_and_limit(self) -> None:
        self._seed_lead_bundle()
        response = self.client.get("/suppression", params={"q": "acme", "limit": 1, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sort"], "desc")
        self.assertEqual(body["limit"], 1)
        self.assertEqual(body["offset"], 0)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["total"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_offset"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["email_or_domain"], "owner@acme.example")

        response2 = self.client.get("/suppression", params={"limit": 1, "offset": 1})
        self.assertEqual(response2.status_code, 200, response2.text)
        body2 = response2.json()
        self.assertEqual(body2["sort"], "desc")
        self.assertEqual(body2["limit"], 1)
        self.assertEqual(body2["offset"], 1)
        self.assertEqual(body2["count"], 1)
        self.assertEqual(body2["total"], 2)
        self.assertFalse(body2["has_more"])
        self.assertIsNone(body2["next_offset"])
        self.assertEqual(len(body2["items"]), 1)
        self.assertEqual(body2["items"][0]["email_or_domain"], "bravo.example")

        asc_response = self.client.get("/suppression", params={"limit": 1, "offset": 0, "sort": "asc"})
        self.assertEqual(asc_response.status_code, 200, asc_response.text)
        asc_body = asc_response.json()
        self.assertEqual(asc_body["sort"], "asc")
        self.assertEqual(asc_body["items"][0]["email_or_domain"], "bravo.example")

    def test_list_suppression_ignores_blank_q(self) -> None:
        self._seed_lead_bundle()

        response = self.client.get("/suppression", params={"q": "   ", "limit": 10, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["count"], 2)

    def test_list_suppression_excludes_blank_legacy_rows(self) -> None:
        from app.models import Suppression

        self._seed_lead_bundle()
        self.db.add(Suppression(email_or_domain="   ", reason="opt_out"))
        self.db.commit()

        response = self.client.get("/suppression", params={"limit": 10, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["count"], 2)
        self.assertEqual({item["email_or_domain"] for item in body["items"]}, {"owner@acme.example", "bravo.example"})

    def test_list_suppression_normalizes_legacy_whitespace_rows(self) -> None:
        from app.models import Suppression

        self._seed_lead_bundle()
        self.db.add(Suppression(email_or_domain="  LeGaCy.ExAmPlE  ", reason="  OpT_OuT  "))
        self.db.commit()

        response = self.client.get("/suppression", params={"q": "legacy", "limit": 10, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["items"][0]["email_or_domain"], "legacy.example")
        self.assertEqual(body["items"][0]["reason"], "opt_out")


if __name__ == "__main__":
    unittest.main()
