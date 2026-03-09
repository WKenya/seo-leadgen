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
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import StaticPool
except Exception as exc:  # noqa: BLE001
    HAS_API_DEPS = False
    IMPORT_ERROR = str(exc)

if HAS_API_DEPS:
    from sqlite_test_shims import install_sqlite_shims

    install_sqlite_shims()


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
            "POSTMARK_WEBHOOK_TOKEN": os.environ.get("POSTMARK_WEBHOOK_TOKEN"),
            "MAILGUN_WEBHOOK_SIGNING_KEY": os.environ.get("MAILGUN_WEBHOOK_SIGNING_KEY"),
            "MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS": os.environ.get("MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"),
            "SENDGRID_WEBHOOK_PUBLIC_KEY": os.environ.get("SENDGRID_WEBHOOK_PUBLIC_KEY"),
            "SENDGRID_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS": os.environ.get("SENDGRID_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"),
        }
        os.environ["WEBHOOK_SHARED_SECRET"] = "test_shared_secret"
        os.environ["WEBHOOK_SIGNATURE_SECRET"] = ""
        os.environ["WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"] = "300"
        os.environ["POSTMARK_WEBHOOK_TOKEN"] = ""
        os.environ["MAILGUN_WEBHOOK_SIGNING_KEY"] = ""
        os.environ["MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"] = "300"
        os.environ["SENDGRID_WEBHOOK_PUBLIC_KEY"] = ""
        os.environ["SENDGRID_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"] = "300"
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
        body = response.json()
        self.assertEqual(body["processed"], 1)
        self.assertEqual(body["processed_by_type"], {"replied": 1})
        self.assertEqual(body["processed_by_provider"], {})
        self.assertEqual(body["rejected_by_reason"], {})

        refreshed = self.db.get(Lead, lead.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, "Replied")
        events = self.db.execute(select(OutreachEvent)).scalars().all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "replied")

    def test_webhook_token_mode_normalizes_provider_field(self) -> None:
        from app.models import OutreachEvent

        lead = self._create_lead()
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={
                "events": [
                    {"lead_id": str(lead.id), "event_type": "replied", "event_id": "evt-provider-1", "provider": "SendGrid"}
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 1)
        self.assertEqual(body["processed_by_provider"], {"sendgrid": 1})
        event = self.db.execute(select(OutreachEvent)).scalar_one_or_none()
        self.assertIsNotNone(event)
        self.assertEqual(event.provider, "sendgrid")
        payload = event.payload or {}
        self.assertEqual(payload.get("provider"), "sendgrid")

    def test_webhook_token_mode_resolves_lead_by_website_domain(self) -> None:
        from app.models import Lead

        lead = Lead(
            id=uuid4(),
            name="Domain Match",
            category="HVAC",
            source="google_places",
            website_url="https://acme.example",
            website_domain="acme.example",
            status="Discovered",
        )
        self.db.add(lead)
        self.db.commit()

        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={"events": [{"email_or_domain": "acme.example", "event_type": "replied", "event_id": "evt-domain-1"}]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 1)
        self.assertEqual(body["rejected_by_reason"], {})

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
        self.assertEqual(body["processed_by_type"], {})
        self.assertEqual(body["processed_by_provider"], {})
        self.assertEqual(body["duplicates"], 1)
        self.assertEqual(body["rejected_by_reason"], {})
        events = self.db.execute(select(OutreachEvent)).scalars().all()
        self.assertEqual(len(events), 1)

    def test_webhook_token_mode_invalid_event_type_tracks_rejected_reason(self) -> None:
        lead = self._create_lead()
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={"events": [{"lead_id": str(lead.id), "event_type": "opened"}]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 0)
        self.assertEqual(body["rejected_by_reason"], {"invalid_event_type": 1})

    def test_webhook_token_mode_normalizes_custom_event_email_or_domain(self) -> None:
        from app.models import Suppression

        lead = self._create_lead(email="owner@acme.example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={
                "events": [
                    {
                        "lead_id": str(lead.id),
                        "event_type": "opt_out",
                        "email_or_domain": " Owner@Acme.Example ",
                        "event_id": "evt-case-1",
                    }
                ]
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.email_or_domain, "owner@acme.example")

    def test_webhook_form_payload_with_invalid_utf8_returns_400(self) -> None:
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={
                "X-Webhook-Token": "test_shared_secret",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            content=b"\xff\xfe",
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("invalid_body", response.text)

    def test_webhook_token_mode_lead_not_found_tracks_rejected_reason(self) -> None:
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={"events": [{"lead_id": str(uuid4()), "event_type": "replied"}]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 0)
        self.assertEqual(body["rejected_by_reason"], {"lead_not_found": 1})

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
        from app.models import Lead, OutreachEvent, Suppression

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
        body = response.json()
        self.assertEqual(body["processed"], 1)
        self.assertEqual(body["processed_by_type"], {"opt_out": 1})
        self.assertEqual(body["processed_by_provider"], {"sendgrid": 1})

        refreshed = self.db.get(Lead, lead.id)
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.email_or_domain, "owner@acme.example")
        self.assertEqual(row.reason, "opt_out")
        event = self.db.execute(select(OutreachEvent)).scalar_one_or_none()
        self.assertIsNotNone(event)
        payload = event.payload or {}
        self.assertEqual(payload.get("provider"), "sendgrid")
        self.assertEqual(payload.get("provider_event_id"), "sg-evt-1")
        self.assertEqual(payload.get("provider_event_name"), "unsubscribe")
        self.assertEqual(payload.get("provider_event_at"), "2023-11-14T22:13:20+00:00")

    def test_webhook_token_mode_resolves_mixed_case_lead_email(self) -> None:
        from app.models import Lead, Suppression

        lead = self._create_lead(email="Owner@Acme.Example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json=[{"email": "owner@acme.example", "event": "unsubscribe", "sg_event_id": "sg-case-1"}],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)

        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.email_or_domain, "owner@acme.example")

    def test_webhook_token_mode_accepts_sendgrid_dropped_event_as_bounced(self) -> None:
        from app.models import Lead, Suppression

        lead = self._create_lead(email="owner@acme.example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json=[{"email": "owner@acme.example", "event": "dropped", "sg_event_id": "sg-drop-1"}],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.reason, "bounced")

    def test_webhook_token_mode_accepts_sendgrid_spam_report_variant(self) -> None:
        from app.models import Lead, Suppression

        lead = self._create_lead(email="owner@acme.example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json=[{"email": "owner@acme.example", "event": "spam_report", "sg_event_id": "sg-spam-1"}],
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.reason, "opt_out")

    def test_webhook_sendgrid_signature_mode_accepts_valid_headers(self) -> None:
        import base64

        from app.settings import get_settings
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        lead = self._create_lead(email="owner@acme.example")
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        os.environ["SENDGRID_WEBHOOK_PUBLIC_KEY"] = public_key_pem
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()

        payload = [{"email": str(lead.email), "event": "unsubscribe", "sg_event_id": "sg-auth-1"}]
        raw = json.dumps(payload).encode("utf-8")
        timestamp = str(int(time.time()))
        sig = private_key.sign(timestamp.encode("utf-8") + raw, ec.ECDSA(hashes.SHA256()))
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={
                "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
                "X-Twilio-Email-Event-Webhook-Signature": base64.b64encode(sig).decode("ascii"),
            },
            content=raw,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)

    def test_webhook_sendgrid_signature_mode_rejects_invalid_signature(self) -> None:
        from app.settings import get_settings
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        self._create_lead(email="owner@acme.example")
        public_key_pem = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        os.environ["SENDGRID_WEBHOOK_PUBLIC_KEY"] = public_key_pem
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()

        response = self.client.post(
            "/webhooks/outreach-events",
            headers={
                "X-Twilio-Email-Event-Webhook-Timestamp": str(int(time.time())),
                "X-Twilio-Email-Event-Webhook-Signature": "bad",
            },
            json=[],
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "invalid_sendgrid_signature")

    def test_webhook_sendgrid_signature_mode_rejects_stale_timestamp(self) -> None:
        import base64

        from app.settings import get_settings
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        self._create_lead(email="owner@acme.example")
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        os.environ["SENDGRID_WEBHOOK_PUBLIC_KEY"] = public_key_pem
        os.environ["SENDGRID_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"] = "1"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()

        payload = [{"email": "owner@acme.example", "event": "unsubscribe", "sg_event_id": "sg-auth-stale"}]
        raw = json.dumps(payload).encode("utf-8")
        timestamp = "1"
        sig = private_key.sign(timestamp.encode("utf-8") + raw, ec.ECDSA(hashes.SHA256()))
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={
                "X-Twilio-Email-Event-Webhook-Timestamp": timestamp,
                "X-Twilio-Email-Event-Webhook-Signature": base64.b64encode(sig).decode("ascii"),
            },
            content=raw,
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "stale_sendgrid_signature_timestamp")

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

    def test_webhook_postmark_token_mode_accepts_valid_header(self) -> None:
        from app.settings import get_settings

        lead = self._create_lead(email="owner@acme.example")
        os.environ["POSTMARK_WEBHOOK_TOKEN"] = "pm-secret"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()

        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Postmark-Server-Token": "pm-secret"},
            json={"RecordType": "Bounce", "MessageID": "pm-auth-1", "Email": str(lead.email)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)

    def test_webhook_postmark_token_mode_rejects_invalid_header(self) -> None:
        from app.settings import get_settings

        self._create_lead(email="owner@acme.example")
        os.environ["POSTMARK_WEBHOOK_TOKEN"] = "pm-secret"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()

        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Postmark-Server-Token": "wrong"},
            json={"RecordType": "Bounce", "MessageID": "pm-auth-2", "Email": "owner@acme.example"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "invalid_postmark_webhook_token")

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

    def test_webhook_token_mode_postmark_subscription_change_false_string_is_noop(self) -> None:
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={
                "RecordType": "SubscriptionChange",
                "MessageID": "pm-sub-0",
                "Email": "owner@acme.example",
                "SuppressSending": "false",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 0)
        self.assertEqual(body["duplicates"], 0)

    def test_webhook_token_mode_postmark_subscription_change_true_string_suppresses(self) -> None:
        from app.models import Lead, Suppression

        lead = self._create_lead(email="owner@acme.example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={
                "RecordType": "SubscriptionChange",
                "MessageID": "pm-sub-1",
                "Email": "owner@acme.example",
                "SuppressSending": "true",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.reason, "opt_out")

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

    def test_webhook_mailgun_signature_mode_accepts_valid_json_signature(self) -> None:
        from app.settings import get_settings
        from app.webhook_auth import compute_mailgun_signature
        import time

        lead = self._create_lead(email="owner@acme.example")
        os.environ["MAILGUN_WEBHOOK_SIGNING_KEY"] = "mg-key"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()
        timestamp = str(int(time.time()))
        token = "abc123"
        sig = compute_mailgun_signature(signing_key="mg-key", timestamp=timestamp, token=token)
        response = self.client.post(
            "/webhooks/outreach-events",
            json={
                "signature": {"timestamp": timestamp, "token": token, "signature": sig},
                "event-data": {"id": "mg-auth-1", "event": "unsubscribed", "recipient": str(lead.email)},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)

    def test_webhook_mailgun_signature_mode_rejects_invalid_signature(self) -> None:
        from app.settings import get_settings
        import time

        self._create_lead(email="owner@acme.example")
        os.environ["MAILGUN_WEBHOOK_SIGNING_KEY"] = "mg-key"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()
        response = self.client.post(
            "/webhooks/outreach-events",
            json={
                "signature": {"timestamp": str(int(time.time())), "token": "abc123", "signature": "bad"},
                "event-data": {"id": "mg-auth-2", "event": "unsubscribed", "recipient": "owner@acme.example"},
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "invalid_mailgun_signature")

    def test_webhook_mailgun_signature_mode_rejects_stale_timestamp(self) -> None:
        from app.settings import get_settings
        from app.webhook_auth import compute_mailgun_signature

        self._create_lead(email="owner@acme.example")
        os.environ["MAILGUN_WEBHOOK_SIGNING_KEY"] = "mg-key"
        os.environ["MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"] = "1"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()
        timestamp = "1"
        token = "abc123"
        sig = compute_mailgun_signature(signing_key="mg-key", timestamp=timestamp, token=token)
        response = self.client.post(
            "/webhooks/outreach-events",
            json={
                "signature": {"timestamp": timestamp, "token": token, "signature": sig},
                "event-data": {"id": "mg-auth-3", "event": "unsubscribed", "recipient": "owner@acme.example"},
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "stale_mailgun_signature_timestamp")

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

    def test_webhook_token_mode_mailgun_failed_temporary_is_noop(self) -> None:
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            json={
                "event-data": {
                    "id": "mg-fail-temp-1",
                    "event": "failed",
                    "severity": "temporary",
                    "recipient": "owner@acme.example",
                }
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["processed"], 0)
        self.assertEqual(body["duplicates"], 0)

    def test_webhook_token_mode_mailgun_legacy_failed_temporary_is_noop(self) -> None:
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            data={
                "event": "failed",
                "severity": "temporary",
                "recipient": "owner@acme.example",
                "event-id": "mg-legacy-temp-1",
                "signature[token]": "x",
                "signature[timestamp]": "1700000000",
                "signature[signature]": "ignored",
            },
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

    def test_webhook_token_mode_accepts_mailgun_legacy_form_fields(self) -> None:
        from app.models import Lead, OutreachEvent, Suppression

        lead = self._create_lead(email="owner@acme.example")
        response = self.client.post(
            "/webhooks/outreach-events",
            headers={"X-Webhook-Token": "test_shared_secret"},
            data={
                "event": "failed",
                "recipient": "owner@acme.example",
                "event-id": "mg-legacy-1",
                "severity": "permanent",
                "signature[token]": "x",
                "signature[timestamp]": "1700000000",
                "signature[signature]": "ignored",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["processed"], 1)
        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        row = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(row)
        self.assertEqual(row.reason, "bounced")
        event = self.db.execute(select(OutreachEvent)).scalar_one_or_none()
        self.assertIsNotNone(event)
        payload = event.payload or {}
        self.assertEqual(payload.get("provider"), "mailgun")
        self.assertEqual(payload.get("provider_event_id"), "mg-legacy-1")
        self.assertEqual(payload.get("provider_event_name"), "failed")
        self.assertIsNone(payload.get("provider_event_at"))

    def test_webhook_mailgun_signature_mode_accepts_form_encoded_top_level_signature_fields(self) -> None:
        import time

        from app.models import Lead, Suppression
        from app.settings import get_settings
        from app.webhook_auth import compute_mailgun_signature

        lead = self._create_lead(email="owner@acme.example")
        os.environ["MAILGUN_WEBHOOK_SIGNING_KEY"] = "mg-key"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()

        timestamp = str(int(time.time()))
        token = "plain-form-token"
        signature = compute_mailgun_signature(signing_key="mg-key", timestamp=timestamp, token=token)

        response = self.client.post(
            "/webhooks/outreach-events",
            data={
                "timestamp": timestamp,
                "token": token,
                "signature": signature,
                "event-data": json.dumps(
                    {
                        "id": "mg-form-plain-1",
                        "event": "unsubscribed",
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

    def test_webhook_mailgun_signature_mode_accepts_legacy_form_fields(self) -> None:
        import time

        from app.models import Lead, Suppression
        from app.settings import get_settings
        from app.webhook_auth import compute_mailgun_signature

        lead = self._create_lead(email="owner@acme.example")
        os.environ["MAILGUN_WEBHOOK_SIGNING_KEY"] = "mg-key"
        os.environ["WEBHOOK_SHARED_SECRET"] = ""
        get_settings.cache_clear()

        timestamp = str(int(time.time()))
        token = "legacy-form-token"
        signature = compute_mailgun_signature(signing_key="mg-key", timestamp=timestamp, token=token)
        response = self.client.post(
            "/webhooks/outreach-events",
            data={
                "timestamp": timestamp,
                "token": token,
                "signature": signature,
                "event": "complained",
                "recipient": "owner@acme.example",
                "event-id": "mg-legacy-auth-1",
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
