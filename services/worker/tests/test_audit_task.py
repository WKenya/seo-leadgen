from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from app.tasks import audit


class _FakeSession:
    def __init__(self, lead: audit.Lead):
        self.lead = lead
        self.commits = 0
        self.added: list[object] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, object_id):  # noqa: ANN001
        if model is audit.Lead and object_id == self.lead.id:
            return self.lead
        return None

    def add(self, value):  # noqa: ANN001
        self.added.append(value)

    def flush(self) -> None:
        return None

    def execute(self, statement):  # noqa: ANN001
        _ = statement
        return None

    def commit(self) -> None:
        self.commits += 1


class AuditTaskTests(unittest.TestCase):
    def test_audit_lead_commits_without_noindex_issue(self) -> None:
        lead_id = uuid4()
        lead = audit.Lead(
            id=lead_id,
            name="Acme HVAC",
            category="HVAC",
            source="test",
            website_url="https://acme.example",
            status="Discovered",
        )
        fake_session = _FakeSession(lead)
        settings = SimpleNamespace(
            crawl_max_pages=10,
            crawl_delay_seconds=0.0,
            crawl_respect_robots=True,
            audit_lighthouse_url="http://audit:8081",
            audit_max_broken_link_issues=10,
        )

        with (
            patch.object(audit, "SessionLocal", return_value=fake_session),
            patch.object(audit, "get_settings", return_value=settings),
            patch.object(
                audit,
                "check_tls",
                return_value={
                    "final_url": "https://acme.example",
                    "https_ok": True,
                    "redirect_chain": [],
                    "cert_error": None,
                    "http_to_https": True,
                },
            ),
            patch.object(
                audit,
                "crawl_site",
                return_value={
                    "visited_pages": 1,
                    "checked_links": 1,
                    "broken_links_count": 0,
                    "broken_links": [],
                    "contact_signals": {
                        "has_contact_page": True,
                        "has_mailto": True,
                        "emails_found": [],
                    },
                    "seo_signals": {
                        "title_present": True,
                        "meta_description_present": True,
                        "robots_noindex": False,
                    },
                },
            ),
            patch.object(audit, "run_lighthouse", return_value=None),
            patch.object(audit, "normalize_lighthouse_summary", return_value=None),
            patch.object(
                audit,
                "capture_homepage_screenshot",
                return_value={"status": "ok", "artifact_path": "/tmp/smoke.png"},
            ),
            patch.object(audit, "aggregate_broken_links", return_value=[]),
            patch.object(audit.celery_app, "send_task") as send_task_mock,
        ):
            result = audit.audit_lead(str(lead_id))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["lead_id"], str(lead_id))
        self.assertEqual(fake_session.commits, 1)
        self.assertEqual(lead.status, "Audited")
        send_task_mock.assert_called_once()

    def test_audit_lead_invalid_uuid_logs_failure(self) -> None:
        with (
            patch.object(audit, "get_settings"),
            patch.object(audit, "log_task_failure_for_lead", return_value=True) as log_failure_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid lead_id"):
                audit.audit_lead("not-a-uuid")

        log_failure_mock.assert_called_once()
        kwargs = log_failure_mock.call_args.kwargs
        self.assertEqual(kwargs["lead_id"], "not-a-uuid")
        self.assertEqual(kwargs["task_name"], "audit_lead")


if __name__ == "__main__":
    unittest.main()
