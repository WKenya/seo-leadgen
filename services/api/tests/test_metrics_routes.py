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
    from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import StaticPool
except Exception as exc:  # noqa: BLE001
    HAS_API_DEPS = False
    IMPORT_ERROR = str(exc)

if HAS_API_DEPS:
    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
        return "JSON"

    @compiles(PGUUID, "sqlite")
    def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001
        return "CHAR(36)"


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
        event1 = OutreachEvent(id=uuid4(), lead_id=lead1.id, type="sent", created_at=now, payload={"x": 1})
        event2 = OutreachEvent(id=uuid4(), lead_id=lead2.id, type="opt_out", created_at=yesterday, payload={"x": 2})

        self.db.add_all([lead1, lead2, audit1, audit2, draft1, draft2, event1, event2])
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
        self.assertEqual(body["events_today"], 1)
        self.assertIn("sent", body["latest_event_types"])
        self.assertIn("opt_out", body["latest_event_types"])


if __name__ == "__main__":
    unittest.main()
