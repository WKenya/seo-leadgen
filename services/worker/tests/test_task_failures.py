from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import uuid4

from app.tasks import task_failures


class _FakeSession:
    def __init__(self, *, lead=None, draft=None):
        self._lead = lead
        self._draft = draft
        self.added = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, model, object_id):  # noqa: ANN001
        if model is task_failures.Lead:
            if self._lead is not None and self._lead.id == object_id:
                return self._lead
            return None
        if model is task_failures.EmailDraft:
            if self._draft is not None and self._draft.id == object_id:
                return self._draft
            return None
        return None

    def add(self, value):  # noqa: ANN001
        self.added.append(value)

    def commit(self):
        self.commits += 1


class _SessionFactory:
    def __init__(self, sessions):
        self._sessions = list(sessions)

    def __call__(self):
        if not self._sessions:
            raise RuntimeError("no fake sessions left")
        return self._sessions.pop(0)


class TaskFailureEventTests(unittest.TestCase):
    def test_log_task_failure_for_lead_writes_outreach_event(self) -> None:
        lead_id = uuid4()
        lead = task_failures.Lead(
            id=lead_id,
            name="Acme HVAC",
            source="test",
            website_url="https://acme.example",
            status="Discovered",
        )
        lookup_session = _FakeSession(lead=lead)
        write_session = _FakeSession()
        factory = _SessionFactory([lookup_session, write_session])
        with patch.object(task_failures, "SessionLocal", factory):
            ok = task_failures.log_task_failure_for_lead(
                lead_id=str(lead_id),
                task_name="audit_lead",
                error=RuntimeError("boom"),
                context={"audit_id": "a1", "skip": None},
            )
        self.assertTrue(ok)
        self.assertEqual(write_session.commits, 1)
        self.assertEqual(len(write_session.added), 1)
        event = write_session.added[0]
        self.assertEqual(event.type, "task_failed")
        self.assertEqual(str(event.lead_id), str(lead_id))
        self.assertEqual(event.payload["task_name"], "audit_lead")
        self.assertEqual(event.payload["error"], "boom")
        self.assertEqual(event.payload["context"], {"audit_id": "a1"})

    def test_log_task_failure_for_draft_resolves_lead_and_writes_event(self) -> None:
        lead_id = uuid4()
        draft_id = uuid4()
        lead = task_failures.Lead(
            id=lead_id,
            name="Acme HVAC",
            source="test",
            website_url="https://acme.example",
            status="Discovered",
        )
        draft = task_failures.EmailDraft(
            id=draft_id,
            lead_id=lead_id,
            audit_id=uuid4(),
            subject="s",
            body_text="b",
        )
        lookup_session = _FakeSession(lead=lead, draft=draft)
        write_session = _FakeSession()
        factory = _SessionFactory([lookup_session, write_session])
        with patch.object(task_failures, "SessionLocal", factory):
            ok = task_failures.log_task_failure_for_draft(
                draft_id=str(draft_id),
                task_name="create_gmail_draft",
                error=RuntimeError("gmail error"),
                context={"draft_id": str(draft_id)},
            )
        self.assertTrue(ok)
        self.assertEqual(write_session.commits, 1)
        self.assertEqual(len(write_session.added), 1)
        event = write_session.added[0]
        self.assertEqual(event.type, "task_failed")
        self.assertEqual(str(event.lead_id), str(lead_id))
        self.assertEqual(event.payload["task_name"], "create_gmail_draft")
        self.assertEqual(event.payload["error"], "gmail error")

    def test_log_task_failure_for_lead_rejects_invalid_id(self) -> None:
        with patch.object(task_failures, "SessionLocal") as session_local:
            ok = task_failures.log_task_failure_for_lead(
                lead_id="not-a-uuid",
                task_name="audit_lead",
                error="boom",
            )
        self.assertFalse(ok)
        session_local.assert_not_called()


if __name__ == "__main__":
    unittest.main()
