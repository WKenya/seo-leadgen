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


class LeadRouteTests(unittest.TestCase):
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
        }
        os.environ.setdefault("WEBHOOK_SHARED_SECRET", "test_shared_secret")
        os.environ.setdefault("WEBHOOK_SIGNATURE_SECRET", "")
        os.environ.setdefault("WEBHOOK_SIGNATURE_TOLERANCE_SECONDS", "300")
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

    def _create_lead(
        self,
        *,
        name: str,
        website_url: str,
        status: str = "Discovered",
        created_at: datetime | None = None,
    ):
        from app.models import Lead

        lead = Lead(
            id=uuid4(),
            name=name,
            category="HVAC",
            source="google_places",
            website_url=website_url,
            status=status,
            created_at=created_at,
        )
        self.db.add(lead)
        self.db.commit()
        return lead

    def test_list_leads_applies_status_q_and_limit_filters(self) -> None:
        now = datetime.now(timezone.utc)
        self._create_lead(name="Alpha HVAC", website_url="https://alpha.example", status="Discovered", created_at=now - timedelta(minutes=3))
        self._create_lead(name="Beta Dental", website_url="https://beta.example", status="Suppressed", created_at=now - timedelta(minutes=2))
        self._create_lead(name="Gamma HVAC", website_url="https://gamma.example", status="Suppressed", created_at=now - timedelta(minutes=1))

        response = self.client.get("/leads", params={"status": "Suppressed", "q": "hvac", "limit": 1, "offset": 0})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status_filter"], "Suppressed")
        self.assertEqual(body["q"], "hvac")
        self.assertEqual(body["sort"], "desc")
        self.assertEqual(body["limit"], 1)
        self.assertEqual(body["offset"], 0)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["total"], 1)
        self.assertFalse(body["has_more"])
        self.assertIsNone(body["next_offset"])
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["name"], "Gamma HVAC")

        response2 = self.client.get("/leads", params={"status": "Suppressed", "q": "hvac", "limit": 1, "offset": 1})
        self.assertEqual(response2.status_code, 200, response2.text)
        body2 = response2.json()
        self.assertEqual(body2["sort"], "desc")
        self.assertEqual(body2["offset"], 1)
        self.assertEqual(body2["count"], 0)
        self.assertEqual(body2["total"], 1)
        self.assertFalse(body2["has_more"])
        self.assertIsNone(body2["next_offset"])
        self.assertEqual(len(body2["items"]), 0)

    def test_get_lead_returns_404_when_missing(self) -> None:
        response = self.client.get(f"/leads/{uuid4()}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"], "lead not found")

    def test_list_lead_audits_returns_only_target_lead(self) -> None:
        from app.models import Audit

        lead1 = self._create_lead(name="Acme", website_url="https://acme.example")
        lead2 = self._create_lead(name="Other", website_url="https://other.example")
        older = datetime.now(timezone.utc) - timedelta(hours=2)
        newer = datetime.now(timezone.utc) - timedelta(hours=1)
        audit1 = Audit(id=uuid4(), lead_id=lead1.id, final_url=lead1.website_url, started_at=older)
        audit2 = Audit(id=uuid4(), lead_id=lead1.id, final_url=lead1.website_url, started_at=newer)
        audit3 = Audit(id=uuid4(), lead_id=lead2.id, final_url=lead2.website_url, started_at=newer)
        self.db.add_all([audit1, audit2, audit3])
        self.db.commit()

        response = self.client.get(f"/leads/{lead1.id}/audits", params={"limit": 1, "offset": 1})
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
        self.assertTrue(all(item["lead_id"] == str(lead1.id) for item in body["items"]))
        self.assertEqual(body["items"][0]["id"], str(audit1.id))

    def test_list_leads_supports_sort_asc(self) -> None:
        now = datetime.now(timezone.utc)
        self._create_lead(name="Zulu", website_url="https://zulu.example", created_at=now - timedelta(minutes=1))
        self._create_lead(name="Alpha", website_url="https://alpha.example", created_at=now - timedelta(minutes=3))
        self._create_lead(name="Mike", website_url="https://mike.example", created_at=now - timedelta(minutes=2))

        response = self.client.get("/leads", params={"limit": 2, "offset": 0, "sort": "asc"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["sort"], "asc")
        self.assertEqual(body["count"], 2)
        self.assertEqual(body["total"], 3)
        self.assertTrue(body["has_more"])
        self.assertEqual(body["next_offset"], 2)
        self.assertEqual([item["name"] for item in body["items"]], ["Alpha", "Mike"])

    def test_pipeline_returns_latest_audit_latest_draft_and_recent_events(self) -> None:
        from app.models import Audit, EmailDraft, OutreachEvent

        lead = self._create_lead(name="Acme", website_url="https://acme.example", status="Draft Ready")
        now = datetime.now(timezone.utc)

        audit_old = Audit(
            id=uuid4(),
            lead_id=lead.id,
            final_url="https://acme.example",
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=2),
        )
        audit_new = Audit(
            id=uuid4(),
            lead_id=lead.id,
            final_url="https://acme.example/final",
            started_at=now - timedelta(hours=1),
            finished_at=now - timedelta(minutes=30),
        )
        draft_old = EmailDraft(
            id=uuid4(),
            lead_id=lead.id,
            audit_id=audit_old.id,
            subject="old",
            body_text="old body",
            created_at=now - timedelta(hours=1),
        )
        draft_new = EmailDraft(
            id=uuid4(),
            lead_id=lead.id,
            audit_id=audit_new.id,
            subject="new",
            body_text="new body",
            created_at=now,
        )
        event_old = OutreachEvent(
            id=uuid4(),
            lead_id=lead.id,
            type="approved",
            payload={"step": 1},
            created_at=now - timedelta(minutes=10),
        )
        event_new = OutreachEvent(
            id=uuid4(),
            lead_id=lead.id,
            type="sent",
            payload={"step": 2},
            created_at=now - timedelta(minutes=1),
        )
        self.db.add_all([audit_old, audit_new, draft_old, draft_new, event_old, event_new])
        self.db.commit()

        response = self.client.get(f"/leads/{lead.id}/pipeline")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["lead"]["id"], str(lead.id))
        self.assertEqual(body["latest_audit"]["id"], str(audit_new.id))
        self.assertEqual(body["latest_audit"]["final_url"], "https://acme.example/final")
        self.assertEqual(body["latest_draft"]["id"], str(draft_new.id))
        self.assertEqual(body["latest_draft"]["subject"], "new")
        self.assertEqual([event["type"] for event in body["recent_events"][:2]], ["sent", "approved"])


if __name__ == "__main__":
    unittest.main()
