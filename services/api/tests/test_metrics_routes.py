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


class MetricsRouteTests(unittest.TestCase):
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

    def test_metrics_summary_counts_statuses_drafts_and_events(self) -> None:
        from app.models import Audit, EmailDraft, Lead, OutreachEvent

        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        lead1 = Lead(id=uuid4(), name="A", source="x", website_url="https://a.example", status="Discovered")
        lead2 = Lead(id=uuid4(), name="B", source="x", website_url="https://b.example", status="Suppressed")
        audit1 = Audit(id=uuid4(), lead_id=lead1.id, final_url=lead1.website_url)
        audit2 = Audit(id=uuid4(), lead_id=lead2.id, final_url=lead2.website_url)
        draft1 = EmailDraft(
            id=uuid4(),
            lead_id=lead1.id,
            audit_id=audit1.id,
            subject="d1",
            body_text="x",
            approved_at=now,
            sent_at=now,
        )
        draft2 = EmailDraft(
            id=uuid4(),
            lead_id=lead2.id,
            audit_id=audit2.id,
            subject="d2",
            body_text="x",
        )
        event1 = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="sent",
            created_at=now,
            payload={"provider": "sendgrid", "provider_event_id": "sg-1"},
        )
        event1b = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="bounced",
            created_at=now,
            payload={"provider": "sendgrid", "provider_event_id": "sg-2"},
        )
        event2 = OutreachEvent(
            id=uuid4(),
            lead_id=lead2.id,
            type="opt_out",
            created_at=yesterday,
            payload={"provider": "mailgun", "provider_event_id": "mg-1"},
        )

        self.db.add_all([lead1, lead2, audit1, audit2, draft1, draft2, event1, event1b, event2])
        self.db.commit()

        response = self.client.get("/metrics/summary")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()

        self.assertIn("as_of", body)
        self.assertEqual(body["leads_by_status"]["Discovered"], 1)
        self.assertEqual(body["leads_by_status"]["Suppressed"], 1)
        self.assertEqual(body["drafts_total"], 2)
        self.assertEqual(body["drafts_approved"], 1)
        self.assertEqual(body["drafts_sent_today"], 1)
        self.assertEqual(body["events_today"], 2)
        self.assertEqual(body["events_today_by_type"], {"bounced": 1, "sent": 1})
        self.assertEqual(body["webhook_events_by_provider_today"], {"sendgrid": 2})
        self.assertEqual(body["webhook_event_types_by_provider_today"], {"sendgrid": {"bounced": 1, "sent": 1}})
        self.assertEqual(body["latest_webhook_providers"], ["sendgrid", "mailgun"])
        self.assertEqual(body["latest_limit"], 10)
        self.assertIn("sent", body["latest_event_types"])
        self.assertIn("opt_out", body["latest_event_types"])
        self.assertIsNone(body["provider_filter"])
        self.assertIsNone(body["webhook_events_today_for_provider"])
        self.assertIsNone(body["webhook_event_types_today_for_provider"])
        self.assertIsNone(body["latest_event_types_for_provider"])

    def test_metrics_summary_provider_filter_returns_provider_scoped_fields(self) -> None:
        from app.models import Audit, EmailDraft, Lead, OutreachEvent

        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)

        lead1 = Lead(id=uuid4(), name="A", source="x", website_url="https://a.example", status="Discovered")
        lead2 = Lead(id=uuid4(), name="B", source="x", website_url="https://b.example", status="Suppressed")
        audit1 = Audit(id=uuid4(), lead_id=lead1.id, final_url=lead1.website_url)
        audit2 = Audit(id=uuid4(), lead_id=lead2.id, final_url=lead2.website_url)
        draft1 = EmailDraft(id=uuid4(), lead_id=lead1.id, audit_id=audit1.id, subject="d1", body_text="x")
        draft2 = EmailDraft(id=uuid4(), lead_id=lead2.id, audit_id=audit2.id, subject="d2", body_text="x")
        event1 = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="sent",
            created_at=now,
            payload={"provider": "sendgrid", "provider_event_id": "sg-1"},
        )
        event2 = OutreachEvent(
            id=uuid4(),
            lead_id=lead1.id,
            type="bounced",
            created_at=now,
            payload={"provider": "sendgrid", "provider_event_id": "sg-2"},
        )
        event3 = OutreachEvent(
            id=uuid4(),
            lead_id=lead2.id,
            type="opt_out",
            created_at=yesterday,
            payload={"provider": "mailgun", "provider_event_id": "mg-1"},
        )
        self.db.add_all([lead1, lead2, audit1, audit2, draft1, draft2, event1, event2, event3])
        self.db.commit()

        response = self.client.get("/metrics/summary", params={"provider": "sendgrid"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["provider_filter"], "sendgrid")
        self.assertEqual(body["webhook_events_today_for_provider"], 2)
        self.assertEqual(body["webhook_event_types_today_for_provider"], {"bounced": 1, "sent": 1})
        self.assertCountEqual(body["latest_event_types_for_provider"], ["bounced", "sent"])

    def test_metrics_summary_latest_limit_trims_latest_lists(self) -> None:
        from app.models import Lead, OutreachEvent

        now = datetime.now(timezone.utc)
        lead = Lead(id=uuid4(), name="A", source="x", website_url="https://a.example", status="Discovered")
        self.db.add(lead)
        self.db.commit()

        for i, event_type in enumerate(["sent", "bounced", "opt_out"], start=1):
            self.db.add(
                OutreachEvent(
                    id=uuid4(),
                    lead_id=lead.id,
                    type=event_type,
                    created_at=now - timedelta(seconds=i),
                    payload={"provider": "sendgrid", "provider_event_id": f"sg-{i}"},
                )
            )
        self.db.commit()

        response = self.client.get("/metrics/summary", params={"latest_limit": 2})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["latest_limit"], 2)
        self.assertEqual(len(body["latest_event_types"]), 2)


if __name__ == "__main__":
    unittest.main()
