from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from app.outreach import policy


class _FakeResult:
    def __init__(self, value: int):
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _FakeSession:
    def __init__(self, value: int):
        self.value = value
        self.statement = None

    def execute(self, statement):  # noqa: ANN001
        self.statement = statement
        return _FakeResult(self.value)


class OutreachPolicyTests(unittest.TestCase):
    def test_sent_count_today_uses_utc_day_window(self) -> None:
        now = datetime(2026, 3, 8, 15, 45, tzinfo=timezone.utc)
        fake_session = _FakeSession(4)

        count = policy.sent_count_today(fake_session, now=now)

        self.assertEqual(count, 4)
        self.assertIsNotNone(fake_session.statement)
        where = list(fake_session.statement._where_criteria)
        self.assertEqual(len(where), 2)
        self.assertEqual(where[0].right.value, datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(where[1].right.value, datetime(2026, 3, 9, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(where[1].right.value - where[0].right.value, timedelta(days=1))

    def test_remaining_daily_send_cap_subtracts_sent_count(self) -> None:
        with patch.object(policy, "sent_count_today", return_value=3):
            remaining = policy.remaining_daily_send_cap(object(), cap=10)
        self.assertEqual(remaining, 7)

    def test_remaining_daily_send_cap_clamps_at_zero(self) -> None:
        with patch.object(policy, "sent_count_today", return_value=12):
            remaining = policy.remaining_daily_send_cap(object(), cap=5)
        self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
