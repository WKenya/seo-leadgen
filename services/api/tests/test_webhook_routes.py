from __future__ import annotations

import json
import os
import sys
import time
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
    from sqlalchemy import create_engine, select
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


class WebhookRouteTests(unittest.TestCase):
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
        os.environ["WEBHOOK_SHARED_SECRET"] = "test_shared_secret"
        os.environ["WEBHOOK_SIGNATURE_SECRET"] = ""
        os.environ["WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"] = "300"
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
            try:
                yield self.db
            finally:
                pass

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

    def _create_lead(self, *, name: str = "Acme HVAC", email: str | None = None):
        from app.models import Lead

        lead = Lead(
            id=uuid4(),
            name=name,
            category="HVAC",
            source="google_places",
            website_url="https://acme.example",
            email=email,
            status="Discovered",
        )
        self.db.add(lead)
        self.db.commit()
        return lead

    def test_webhook_token_mode_processes_replied_event_and_updates_status(self) -> None:
        from app.models import Lead, OutreachEvent

        lead = self._create_lead()
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={"events": [{"lead_id": str(lead.id), "event_type": "replied"}]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)

        refreshed = self.db.get(Lead, lead.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, "Replied")
        events = self.db.execute(select(OutreachEvent)).scalars().all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "replied")

    def test_webhook_duplicate_event_id_is_counted_and_not_reinserted(self) -> None:
        from app.models import OutreachEvent

        lead = self._create_lead()
        payload = {"events": [{"lead_id": str(lead.id), "event_type": "replied", "event_id": "evt-1"}]}
        headers = {"X-Webhook-Token": "test_shared_secret"}
        first = self.client.post("/webhooks/outreach-events", headers=headers, json=payload)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post("/webhooks/outreach-events", headers=headers, json=payload)
        self.assertEqual(second.status_code, 200, second.text)
        body = second.json()
        self.assertEqual(body["processed"], 0)
        self.assertEqual(body["duplicates"], 1)
        events = self.db.execute(select(OutreachEvent)).scalars().all()
        self.assertEqual(len(events), 1)

    def test_webhook_hmac_mode_accepts_signed_request(self) -> None:
        from app.settings import get_settings
        from app.webhook_auth import compute_signature

        lead = self._create_lead()
        os.environ["WEBHOOK_SIGNATURE_SECRET"] = "sig_secret"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()

        payload = {"events": [{"lead_id": str(lead.id), "event_type": "replied", "event_id": "evt-hmac"}]}
        raw = json.dumps(payload).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = compute_signature(secret="sig_secret", body=raw, timestamp=int(timestamp))
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Signature": f"sha256={signature}",
            },
            content=raw,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)

    def test_webhook_hmac_mode_rejects_stale_timestamp(self) -> None:
        from app.settings import get_settings
        from app.webhook_auth import compute_signature

        self._create_lead()
        os.environ["WEBHOOK_SIGNATURE_SECRET"] = "sig_secret"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        os.environ["WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"] = "1"
        get_settings.cache_clear()

        payload = {"events": []}
        raw = json.dumps(payload).encode("utf-8")
        timestamp = "1"
        signature = compute_signature(secret="sig_secret", body=raw, timestamp=int(timestamp))
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Signature": f"sha256={signature}",
            },
            content=raw,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "stale_webhook_timestamp")

    def test_webhook_token_mode_accepts_sendgrid_array_payload_and_suppresses(self) -> None:
        from app.models import Lead, Suppression

        lead = self._create_lead(email="owner@acme.example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json=[
                {
                    "email": "owner@acme.example",
                    "event": "unsubscribe",
                    "sg_event_id": "sg-evt-1",
                    "timestamp": 1700000000,
                }
            ],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)

        refreshed = self.db.get(Lead, lead.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.email_or_domain, "owner@acme.example")
        self.assertEqual(row.reason, "opt_out")

    def test_webhook_token_mode_sendgrid_unmapped_event_is_noop(self) -> None:
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json=[{"email": "owner@acme.example", "event": "open", "sg_event_id": "sg-open-1"}],
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 0)
        self.assertEqual(body["duplicates"], 0)
        self.assertEqual(body["rejected"], [])

    def test_webhook_token_mode_accepts_postmark_bounce_payload(self) -> None:
        from app.models import Lead, Suppression

        lead = self._create_lead(email="owner@acme.example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={
                "RecordType": "Bounce",
                "MessageID": "pm-1",
                "Email": "owner@acme.example",
                "Type": "HardBounce",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.reason, "bounced")

    def test_webhook_token_mode_postmark_unmapped_event_is_noop(self) -> None:
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={"RecordType": "Open", "MessageID": "pm-open-1", "Email": "owner@acme.example"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 0)
        self.assertEqual(body["duplicates"], 0)

    def test_webhook_token_mode_accepts_mailgun_event_data_payload(self) -> None:
        from app.models import Lead, Suppression

        lead = self._create_lead(email="owner@acme.example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={
                "signature": {"timestamp": "1700000000", "token": "x", "signature": "ignored"},
                "event-data": {
                    "id": "mg-evt-1",
                    "event": "unsubscribed",
                    "recipient": "owner@acme.example",
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.reason, "opt_out")

    def test_webhook_token_mode_mailgun_unmapped_event_is_noop(self) -> None:
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={"event-data": {"id": "mg-open-1", "event": "opened", "recipient": "owner@acme.example"}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 0)
        self.assertEqual(body["duplicates"], 0)

    def test_webhook_token_mode_accepts_mailgun_form_encoded_event_data(self) -> None:
        from app.models import Lead, Suppression

        lead = self._create_lead(email="owner@acme.example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            data={
                "signature[token]": "x",
                "signature[timestamp]": "1700000000",
                "signature[signature]": "ignored",
                "event-data": json.dumps(
                    {
                        "id": "mg-form-1",
                        "event": "complained",
                        "recipient": "owner@acme.example",
                    }
                ),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.reason, "opt_out")


if __name__ == "__main__":
    unittest.main()
