from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.llm.schemas import DraftOutput, QuickWin
from app.tasks import summarize


class _FakeIssueResult:
    def __init__(self, issues):
        self._issues = issues

    def scalars(self):
        return self

    def all(self):
        return list(self._issues)


class _FakeSession:
    def __init__(self, lead: summarize.Lead, audit: summarize.Audit, issues: list[summarize.Issue]):
        self.lead = lead
        self.audit = audit
        self.issues = issues
        self.closed = False
        self.commits = 0
        self.added: list[object] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        return False

    def _assert_open(self) -> None:
        if self.closed:
            raise RuntimeError("session closed")

    def get(self, model, object_id):  # noqa: ANN001
        self._assert_open()
        if model is summarize.Lead and object_id == self.lead.id:
            return self.lead
        if model is summarize.Audit and object_id == self.audit.id:
            return self.audit
        return None

    def execute(self, statement):  # noqa: ANN001
        _ = statement
        self._assert_open()
        return _FakeIssueResult(self.issues)

    def add(self, value):  # noqa: ANN001
        self._assert_open()
        self.added.append(value)

    def commit(self) -> None:
        self._assert_open()
        self.commits += 1

    def refresh(self, value):  # noqa: ANN001
        _ = value
        self._assert_open()


class _FakeScalarResult:
    def __init__(self, row):  # noqa: ANN001
        self.row = row

    def scalar_one_or_none(self):  # noqa: ANN001
        return self.row


class _CaseAwareSuppressionSession:
    def __init__(self, stored_values: list[str]):
        self.stored_values = stored_values

    def execute(self, statement):  # noqa: ANN001
        where = list(statement._where_criteria)
        criterion = where[0]
        is_lower_query = getattr(criterion.left, "name", "") == "lower"
        candidates = [str(value) for value in criterion.right.value]
        for stored in self.stored_values:
            probe = stored.lower() if is_lower_query else stored
            if probe in candidates:
                return _FakeScalarResult(object())
        return _FakeScalarResult(None)


class SummarizeTaskTests(unittest.TestCase):
    def test_summarize_uses_session_only_inside_context(self) -> None:
        lead_id = uuid4()
        audit_id = uuid4()
        lead = summarize.Lead(
            id=lead_id,
            name="Acme HVAC",
            category="HVAC",
            source="test",
            website_url="https://acme.example",
            status="Audited",
        )
        audit = summarize.Audit(
            id=audit_id,
            lead_id=lead_id,
            started_at=datetime.now(timezone.utc),
            final_url="https://acme.example",
        )
        fake_session = _FakeSession(lead=lead, audit=audit, issues=[])
        settings = SimpleNamespace(openai_api_key=None, openai_model=None, openai_base_url=None)
        draft_output = DraftOutput(
            lead_profile="This is a regression-safe fallback profile for summarize task tests.",
            quick_wins=[
                QuickWin(
                    title="Fix one issue",
                    why_it_matters="Improves trust and conversion.",
                    how_to_fix="Apply a scoped change and verify.",
                )
            ],
            email_subject="Quick fix for Acme HVAC",
            email_body_text="Hi Acme HVAC,\n\nOne fast fix can improve your site.\n\nThanks.",
            claims_used=[],
        )

        with (
            patch.object(summarize, "SessionLocal", return_value=fake_session),
            patch.object(summarize, "get_settings", return_value=settings),
            patch.object(summarize, "_is_suppressed", return_value=False),
            patch.object(summarize, "_build_fallback_draft", return_value=draft_output),
            patch.object(summarize, "log_task_failure_for_lead", return_value=False),
            patch.object(summarize.celery_app, "send_task") as send_task_mock,
        ):
            result = summarize.summarize_and_draft(str(lead_id), str(audit_id))

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["lead_id"], str(lead_id))
        self.assertEqual(result["audit_id"], str(audit_id))
        self.assertEqual(fake_session.commits, 2)
        self.assertTrue(fake_session.closed)
        self.assertEqual(lead.status, "Draft Ready")
        self.assertTrue(any(isinstance(item, summarize.EmailDraft) for item in fake_session.added))
        self.assertEqual(send_task_mock.call_count, 2)

    def test_summarize_invalid_lead_uuid_logs_failure(self) -> None:
        with (
            patch.object(summarize, "get_settings"),
            patch.object(summarize, "log_task_failure_for_lead", return_value=True) as log_failure_mock,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid lead_id"):
                summarize.summarize_and_draft("not-a-uuid", str(uuid4()))

        log_failure_mock.assert_called_once()
        kwargs = log_failure_mock.call_args.kwargs
        self.assertEqual(kwargs["lead_id"], "not-a-uuid")
        self.assertEqual(kwargs["task_name"], "summarize_and_draft")

    def test_is_suppressed_matches_mixed_case_stored_values(self) -> None:
        lead = summarize.Lead(
            id=uuid4(),
            name="Acme HVAC",
            category="HVAC",
            source="test",
            website_url="https://acme.example",
            email="owner@acme.example",
            status="Audited",
        )
        session = _CaseAwareSuppressionSession(stored_values=["Owner@Acme.Example"])
        self.assertTrue(summarize._is_suppressed(session, lead))


if __name__ == "__main__":
    unittest.main()
