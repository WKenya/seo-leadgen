from __future__ import annotations

import base64
import sys
from pathlib import Path
import unittest

WORKER_ROOT = Path(__file__).resolve().parents[1]
if str(WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKER_ROOT))

from app.outreach.gmail_api import build_gmail_raw_message  # noqa: E402


class GmailApiTests(unittest.TestCase):
    def test_build_gmail_raw_message_contains_headers_and_body(self) -> None:
        raw = build_gmail_raw_message(
            sender_name="Wes",
            sender_email="wes@example.com",
            to_email="lead@example.com",
            subject="Quick fixes",
            body_text="Hello\nLine2",
        )
        padded = raw + "=" * ((4 - len(raw) % 4) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        self.assertIn("From: Wes <wes@example.com>", decoded)
        self.assertIn("To: lead@example.com", decoded)
        self.assertIn("Subject: Quick fixes", decoded)
        self.assertIn("Hello", decoded)
        self.assertNotIn("+", raw)
        self.assertNotIn("/", raw)


if __name__ == "__main__":
    unittest.main()

