from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import uuid4

from app.tasks import suppression as suppression_task


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeSession:
    def __init__(self, lead: suppression_task.Lead, *, existing_suppression_id=None):
        self.lead = lead
        self.existing_suppression_id = existing_suppression_id
        self.added: list[object] = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, object_id):  # noqa: ANN001
        if model is suppression_task.Lead and object_id == self.lead.id:
            return self.lead
        return None

    def execute(self, statement):  # noqa: ANN001
        _ = statement
        return _ScalarResult(self.existing_suppression_id)

    def add(self, value):  # noqa: ANN001
        self.added.append(value)

    def commit(self) -> None:
        self.commits += 1


class SuppressionTaskTests(unittest.TestCase):
    def test_apply_suppression_creates_row_and_marks_lead(self) -> None:
        lead = suppression_task.Lead(
            id=uuid4(),
            name="Acme HVAC",
            category="HVAC",
            source="test",
            website_url="https://acme.example",
            email="owner@acme.example",
            status="Discovered",
        )
        fake_session = _FakeSession(lead)

        with (
            patch.object(suppression_task, "SessionLocal", return_value=fake_session),
            patch.object(suppression_task, "log_task_failure_for_lead", return_value=False),
        ):
            result = suppression_task.apply_suppression(str(lead.id))

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["created"])
        self.assertEqual(lead.status, "Suppressed")
        self.assertEqual(fake_session.commits, 1)
        self.assertTrue(any(isinstance(item, suppression_task.Suppression) for item in fake_session.added))
        self.assertTrue(
            any(
                isinstance(item, suppression_task.OutreachEvent) and item.type == "suppression_applied"
                for item in fake_session.added
            )
        )

    def test_apply_suppression_skips_insert_when_existing_row_present(self) -> None:
        lead = suppression_task.Lead(
            id=uuid4(),
            name="Acme HVAC",
            category="HVAC",
            source="test",
            website_url="https://acme.example",
            email="owner@acme.example",
            status="Discovered",
        )
        fake_session = _FakeSession(lead, existing_suppression_id=uuid4())

        with (
            patch.object(suppression_task, "SessionLocal", return_value=fake_session),
            patch.object(suppression_task, "log_task_failure_for_lead", return_value=False),
        ):
            result = suppression_task.apply_suppression(str(lead.id))

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["created"])
        self.assertFalse(any(isinstance(item, suppression_task.Suppression) for item in fake_session.added))
        self.assertEqual(lead.status, "Suppressed")

    def test_apply_suppression_returns_missing_target_when_lead_has_no_contact(self) -> None:
        lead = suppression_task.Lead(
            id=uuid4(),
            name="Acme HVAC",
            category="HVAC",
            source="test",
            website_url=None,
            website_domain=None,
            email=None,
            status="Discovered",
        )
        fake_session = _FakeSession(lead)

        with (
            patch.object(suppression_task, "SessionLocal", return_value=fake_session),
            patch.object(suppression_task, "log_task_failure_for_lead", return_value=False),
        ):
            result = suppression_task.apply_suppression(str(lead.id))

        self.assertEqual(result["status"], "missing_target")
        self.assertEqual(fake_session.commits, 0)


if __name__ == "__main__":
    unittest.main()
