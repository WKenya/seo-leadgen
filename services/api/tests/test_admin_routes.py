from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
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


class AdminRouteTests(unittest.TestCase):
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
            "DAILY_SEND_CAP": os.environ.get("DAILY_SEND_CAP"),
            "WEBHOOK_SHARED_SECRET": os.environ.get("WEBHOOK_SHARED_SECRET"),
            "WEBHOOK_SIGNATURE_SECRET": os.environ.get("WEBHOOK_SIGNATURE_SECRET"),
            "WEBHOOK_SIGNATURE_TOLERANCE_SECONDS": os.environ.get("WEBHOOK_SIGNATURE_TOLERANCE_SECONDS"),
        }
        os.environ["DAILY_SEND_CAP"] = "5"
        # Keep webhook auth envs stable; app imports all routers in create_app.
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

    def _create_lead_with_draft(self, *, lead_email: str | None = "owner@acme.example"):
        from app.models import Audit, EmailDraft, Lead

        lead = Lead(
            id=uuid4(),
            name="Acme HVAC",
            category="HVAC",
            source="google_places",
            website_url="https://acme.example",
            email=lead_email,
            status="Draft Ready",
        )
        audit = Audit(id=uuid4(), lead_id=lead.id, final_url=lead.website_url)
        draft = EmailDraft(
            id=uuid4(),
            lead_id=lead.id,
            audit_id=audit.id,
            subject="Quick website fixes",
            body_text="Hi there",
        )
        self.db.add(lead)
        self.db.add(audit)
        self.db.add(draft)
        self.db.commit()
        return lead, audit, draft

    def test_approve_draft_marks_approved_and_sets_lead_status(self) -> None:
        from app.models import EmailDraft, Lead, OutreachEvent

        lead, _, draft = self._create_lead_with_draft()
        response = self.client.post(f"/admin/approve-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "approved")

        refreshed_draft = self.db.get(EmailDraft, draft.id)
        refreshed_lead = self.db.get(Lead, lead.id)
        self.assertIsNotNone(refreshed_draft)
        self.assertIsNotNone(refreshed_draft.approved_at)
        self.assertEqual(refreshed_lead.status, "Approved to Send")
        events = self.db.execute(select(OutreachEvent)).scalars().all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "approved")

    def test_approve_draft_blocked_when_suppressed(self) -> None:
        from app.models import Lead, OutreachEvent, Suppression

        lead, _, draft = self._create_lead_with_draft()
        self.db.add(Suppression(email_or_domain="owner@acme.example", reason="opt_out"))
        self.db.commit()

        response = self.client.post(f"/admin/approve-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        refreshed_lead = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed_lead.status, "Suppressed")
        events = self.db.execute(select(OutreachEvent)).scalars().all()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "approved_blocked_suppressed")

    def test_approve_draft_blocked_when_suppression_row_is_mixed_case(self) -> None:
        from app.models import Lead, Suppression

        lead, _, draft = self._create_lead_with_draft()
        self.db.add(Suppression(email_or_domain="  Owner@Acme.Example  ", reason="opt_out"))
        self.db.commit()

        response = self.client.post(f"/admin/approve-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        refreshed_lead = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed_lead.status, "Suppressed")

    def test_approve_draft_blocked_when_suppressed_by_schemeless_website_url_domain(self) -> None:
        from app.models import Lead, Suppression

        lead, _, draft = self._create_lead_with_draft(lead_email=None)
        lead.website_domain = None
        lead.website_url = "  Acme.Example/path  "
        self.db.add(Suppression(email_or_domain="acme.example", reason="opt_out"))
        self.db.commit()

        response = self.client.post(f"/admin/approve-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        refreshed_lead = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed_lead.status, "Suppressed")

    def test_approve_draft_blocked_when_suppressed_by_website_url_with_port(self) -> None:
        from app.models import Lead, Suppression

        lead, _, draft = self._create_lead_with_draft(lead_email=None)
        lead.website_domain = None
        lead.website_url = "https://acme.example:443/path"
        self.db.add(Suppression(email_or_domain="acme.example", reason="opt_out"))
        self.db.commit()

        response = self.client.post(f"/admin/approve-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        refreshed_lead = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed_lead.status, "Suppressed")

    def test_approve_draft_blocked_when_suppression_row_is_legacy_url(self) -> None:
        from app.models import Lead, Suppression

        lead, _, draft = self._create_lead_with_draft(lead_email=None)
        lead.website_domain = None
        lead.website_url = "https://acme.example/path"
        self.db.add(Suppression(email_or_domain="https://Acme.Example/legacy", reason="opt_out"))
        self.db.commit()

        response = self.client.post(f"/admin/approve-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        refreshed_lead = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed_lead.status, "Suppressed")

    def test_approve_draft_blocked_when_suppressed_by_website_domain_with_port(self) -> None:
        from app.models import Lead, Suppression

        lead, _, draft = self._create_lead_with_draft(lead_email=None)
        lead.website_domain = "Acme.Example:443"
        lead.website_url = "https://different.example/path"
        self.db.add(Suppression(email_or_domain="acme.example", reason="opt_out"))
        self.db.commit()

        response = self.client.post(f"/admin/approve-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        refreshed_lead = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed_lead.status, "Suppressed")

    def test_send_draft_requires_approval(self) -> None:
        _, _, draft = self._create_lead_with_draft()
        response = self.client.post(f"/admin/send-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "not_approved")

    def test_send_draft_marks_sent_when_approved(self) -> None:
        from app.models import EmailDraft, Lead, OutreachEvent

        lead, _, draft = self._create_lead_with_draft()
        self.client.post(f"/admin/approve-draft/{draft.id}")

        response = self.client.post(f"/admin/send-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "sent_stubbed")

        refreshed_draft = self.db.get(EmailDraft, draft.id)
        refreshed_lead = self.db.get(Lead, lead.id)
        self.assertIsNotNone(refreshed_draft.sent_at)
        self.assertEqual(refreshed_lead.status, "Sent")
        events = self.db.execute(select(OutreachEvent).order_by(OutreachEvent.created_at.asc())).scalars().all()
        self.assertEqual(events[-1].type, "sent")
        self.assertEqual((events[-1].payload or {}).get("mode"), "manual_stub")

    def test_send_draft_enforces_daily_cap(self) -> None:
        from app.models import EmailDraft, OutreachEvent
        from app.settings import get_settings

        lead, audit, draft = self._create_lead_with_draft()
        self.client.post(f"/admin/approve-draft/{draft.id}")

        os.environ["DAILY_SEND_CAP"] = "1"
        get_settings.cache_clear()

        sent_draft = EmailDraft(
            id=uuid4(),
            lead_id=lead.id,
            audit_id=audit.id,
            subject="Old send",
            body_text="sent",
            approved_at=datetime.now(timezone.utc),
            sent_at=datetime.now(timezone.utc),
        )
        self.db.add(sent_draft)
        self.db.commit()

        response = self.client.post(f"/admin/send-draft/{draft.id}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "daily_cap_reached")
        events = self.db.execute(select(OutreachEvent)).scalars().all()
        self.assertTrue(any(event.type == "send_blocked_cap" for event in events))

    def test_record_event_replied_updates_status(self) -> None:
        from app.models import Lead, OutreachEvent

        lead, _, _ = self._create_lead_with_draft()
        response = self.client.post(
            f"/admin/record-event/{lead.id}",
            json={"event_type": "replied", "note": "Customer replied"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "recorded")
        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Replied")
        events = self.db.execute(select(OutreachEvent)).scalars().all()
        self.assertTrue(any(event.type == "replied" for event in events))

    def test_record_event_opt_out_creates_suppression(self) -> None:
        from app.models import Lead, Suppression

        lead, _, _ = self._create_lead_with_draft()
        response = self.client.post(
            f"/admin/record-event/{lead.id}",
            json={"event_type": "opt_out", "note": "Unsubscribe"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "recorded")
        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)
        self.assertEqual(suppression.email_or_domain, "owner@acme.example")
        self.assertEqual(suppression.reason, "opt_out")

    def test_record_event_invalid_type_is_rejected(self) -> None:
        lead, _, _ = self._create_lead_with_draft()
        response = self.client.post(
            f"/admin/record-event/{lead.id}",
            json={"event_type": "opened"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "invalid_event_type")

    def test_mark_optout_then_unsuppress_restores_status(self) -> None:
        from app.models import Lead, OutreachEvent, Suppression

        lead, _, _ = self._create_lead_with_draft()
        mark = self.client.post(f"/admin/mark-optout/{lead.id}", json={"reason": "manual"})
        self.assertEqual(mark.status_code, 200, mark.text)
        self.assertEqual(mark.json()["status"], "suppressed")

        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")
        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)

        unmark = self.client.post(f"/admin/unsuppress/{lead.id}", json={})
        self.assertEqual(unmark.status_code, 200, unmark.text)
        self.assertEqual(unmark.json()["status"], "unsuppressed")

        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Discovered")
        remaining = self.db.execute(select(Suppression)).scalars().all()
        self.assertEqual(len(remaining), 0)
        events = self.db.execute(select(OutreachEvent)).scalars().all()
        self.assertTrue(any(event.type == "opt_out" for event in events))
        self.assertTrue(any(event.type == "unsuppress" for event in events))

    def test_unsuppress_restores_discovered_for_mixed_case_suppressed_status(self) -> None:
        from app.models import Lead, Suppression

        lead, _, _ = self._create_lead_with_draft()
        lead.status = "sUpPrEsSeD"
        self.db.add(Suppression(email_or_domain="  owner@acme.example  ", reason="opt_out"))
        self.db.commit()

        response = self.client.post(f"/admin/unsuppress/{lead.id}", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "unsuppressed")

        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Discovered")

    def test_unsuppress_removes_duplicate_rows_for_same_normalized_value(self) -> None:
        from app.models import Suppression

        lead, _, _ = self._create_lead_with_draft()
        self.db.add(Suppression(email_or_domain="  owner@acme.example  ", reason="opt_out"))
        self.db.add(Suppression(email_or_domain="owner@acme.example", reason="manual"))
        self.db.commit()

        response = self.client.post(f"/admin/unsuppress/{lead.id}", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "unsuppressed")

        rows = self.db.execute(select(Suppression)).scalars().all()
        self.assertEqual(len(rows), 0)

    def test_mark_optout_avoids_duplicate_with_legacy_whitespace_suppression(self) -> None:
        from app.models import Suppression

        lead, _, _ = self._create_lead_with_draft()
        self.db.add(Suppression(email_or_domain="  owner@acme.example  ", reason="opt_out"))
        self.db.commit()

        response = self.client.post(f"/admin/mark-optout/{lead.id}", json={"reason": "manual"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        rows = self.db.execute(select(Suppression)).scalars().all()
        self.assertEqual(len(rows), 1)

    def test_mark_optout_normalizes_email_or_domain(self) -> None:
        from app.models import Suppression

        lead, _, _ = self._create_lead_with_draft()
        response = self.client.post(
            f"/admin/mark-optout/{lead.id}",
            json={"reason": "manual", "email_or_domain": " Owner@Acme.Example "},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)
        self.assertEqual(suppression.email_or_domain, "owner@acme.example")

    def test_mark_optout_normalizes_url_email_or_domain_to_hostname(self) -> None:
        from app.models import Suppression

        lead, _, _ = self._create_lead_with_draft()
        response = self.client.post(
            f"/admin/mark-optout/{lead.id}",
            json={"reason": "manual", "email_or_domain": " https://Acme.Example/path "},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)
        self.assertEqual(suppression.email_or_domain, "acme.example")

    def test_mark_optout_normalizes_url_with_userinfo_to_hostname(self) -> None:
        from app.models import Suppression

        lead, _, _ = self._create_lead_with_draft()
        response = self.client.post(
            f"/admin/mark-optout/{lead.id}",
            json={"reason": "manual", "email_or_domain": " https://user@Acme.Example/path "},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)
        self.assertEqual(suppression.email_or_domain, "acme.example")

    def test_mark_optout_normalizes_reason(self) -> None:
        from app.models import OutreachEvent, Suppression

        lead, _, _ = self._create_lead_with_draft()
        response = self.client.post(
            f"/admin/mark-optout/{lead.id}",
            json={"reason": "  MANUAL  "},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)
        self.assertEqual(suppression.reason, "manual")

        events = self.db.execute(select(OutreachEvent).where(OutreachEvent.type == "opt_out")).scalars().all()
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].payload or {}).get("reason"), "manual")

    def test_mark_optout_uses_whitespace_padded_website_url_domain_fallback(self) -> None:
        from app.models import Lead, Suppression

        lead, _, _ = self._create_lead_with_draft(lead_email=None)
        lead.website_domain = None
        lead.website_url = "  https://acme.example/path  "
        self.db.commit()

        response = self.client.post(f"/admin/mark-optout/{lead.id}", json={"reason": "manual"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)
        self.assertEqual(suppression.email_or_domain, "acme.example")

        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")

    def test_mark_optout_uses_schemeless_website_url_domain_fallback(self) -> None:
        from app.models import Lead, Suppression

        lead, _, _ = self._create_lead_with_draft(lead_email=None)
        lead.website_domain = None
        lead.website_url = "  Acme.Example/path  "
        self.db.commit()

        response = self.client.post(f"/admin/mark-optout/{lead.id}", json={"reason": "manual"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)
        self.assertEqual(suppression.email_or_domain, "acme.example")

        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")

    def test_mark_optout_falls_back_when_email_is_whitespace(self) -> None:
        from app.models import Lead, Suppression

        lead, _, _ = self._create_lead_with_draft(lead_email="   ")
        lead.website_domain = "  Acme.Example  "
        self.db.commit()

        response = self.client.post(f"/admin/mark-optout/{lead.id}", json={"reason": "manual"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "suppressed")

        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)
        self.assertEqual(suppression.email_or_domain, "acme.example")

        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")

    def test_record_event_opt_out_falls_back_from_blank_email_to_website_url_domain(self) -> None:
        from app.models import Lead, Suppression

        lead, _, _ = self._create_lead_with_draft(lead_email="   ")
        lead.website_domain = None
        lead.website_url = "  https://acme.example/path  "
        self.db.commit()

        response = self.client.post(
            f"/admin/record-event/{lead.id}",
            json={"event_type": "opt_out", "note": "Unsubscribe"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "recorded")

        suppression = self.db.execute(select(Suppression)).scalar_one_or_none()
        self.assertIsNotNone(suppression)
        self.assertEqual(suppression.email_or_domain, "acme.example")

        refreshed = self.db.get(Lead, lead.id)
        self.assertEqual(refreshed.status, "Suppressed")

    def test_run_discovery_batch_queues_nonblank_categories(self) -> None:
        calls: list[tuple[str, dict[str, object] | None]] = []

        def _fake_send_task(name: str, kwargs: dict[str, object] | None = None):
            calls.append((name, kwargs))
            return SimpleNamespace(id=f"task-{len(calls)}")

        with patch("app.routes.admin.celery_client.send_task", side_effect=_fake_send_task):
            response = self.client.post(
                "/admin/run-discovery-batch",
                json={
                    "city": "Cleveland, OH",
                    "categories": ["HVAC", " ", "Dentist"],
                    "radius_meters": 10000,
                    "limit": 7,
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["count"], 2)
        self.assertEqual([item["category"] for item in body["items"]], ["HVAC", "Dentist"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(name == "discover_leads" for name, _ in calls))
        self.assertEqual(calls[0][1]["radius_meters"], 10000)
        self.assertEqual(calls[0][1]["limit"], 7)

    def test_run_audit_batch_filters_by_status(self) -> None:
        from app.models import Lead

        discovered = Lead(
            id=uuid4(),
            name="Disco",
            category="HVAC",
            source="google_places",
            website_url="https://d.example",
            status="  DiScOvErEd  ",
        )
        suppressed = Lead(
            id=uuid4(),
            name="Supp",
            category="HVAC",
            source="google_places",
            website_url="https://s.example",
            status="Suppressed",
        )
        self.db.add(discovered)
        self.db.add(suppressed)
        self.db.commit()

        calls: list[tuple[str, dict[str, object] | None]] = []

        def _fake_send_task(name: str, kwargs: dict[str, object] | None = None):
            calls.append((name, kwargs))
            return SimpleNamespace(id=f"audit-{len(calls)}")

        with patch("app.routes.admin.celery_client.send_task", side_effect=_fake_send_task):
            response = self.client.post(
                "/admin/run-audit-batch",
                json={"statuses": ["discovered"], "limit": 10},
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "audit_lead")
        self.assertEqual(calls[0][1]["lead_id"], str(discovered.id))
        self.assertEqual(body["items"][0]["lead_id"], str(discovered.id))

    def test_other_admin_queue_endpoints_enqueue_expected_tasks(self) -> None:
        calls: list[tuple[str, dict[str, object] | None]] = []

        def _fake_send_task(name: str, kwargs: dict[str, object] | None = None):
            calls.append((name, kwargs))
            return SimpleNamespace(id=f"task-{len(calls)}")

        with patch("app.routes.admin.celery_client.send_task", side_effect=_fake_send_task):
            discovery = self.client.post(
                "/admin/run-discovery",
                params={
                    "city": "Akron, OH",
                    "category": "Plumber",
                    "radius_meters": 5000,
                    "limit": 3,
                },
            )
            self.assertEqual(discovery.status_code, 200, discovery.text)
            self.assertEqual(discovery.json()["status"], "queued")

            run_audit = self.client.post("/admin/run-audit/lead-123")
            self.assertEqual(run_audit.status_code, 200, run_audit.text)
            self.assertEqual(run_audit.json()["lead_id"], "lead-123")

            summarize = self.client.post("/admin/run-summarize/lead-123/audit-456")
            self.assertEqual(summarize.status_code, 200, summarize.text)
            self.assertEqual(summarize.json()["audit_id"], "audit-456")

            notion_sync = self.client.post(
                "/admin/run-notion-sync/lead-123",
                params={"audit_id": "audit-456", "draft_id": "draft-789"},
            )
            self.assertEqual(notion_sync.status_code, 200, notion_sync.text)
            self.assertEqual(notion_sync.json()["lead_id"], "lead-123")

            gmail = self.client.post("/admin/create-gmail-draft/draft-789")
            self.assertEqual(gmail.status_code, 200, gmail.text)
            self.assertEqual(gmail.json()["draft_id"], "draft-789")

        self.assertEqual(
            calls,
            [
                (
                    "discover_leads",
                    {"city": "Akron, OH", "category": "Plumber", "radius_meters": 5000, "limit": 3},
                ),
                ("audit_lead", {"lead_id": "lead-123"}),
                ("summarize_and_draft", {"lead_id": "lead-123", "audit_id": "audit-456"}),
                ("sync_notion", {"lead_id": "lead-123", "audit_id": "audit-456", "draft_id": "draft-789"}),
                ("create_gmail_draft", {"draft_id": "draft-789"}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
