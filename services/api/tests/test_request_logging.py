from __future__ import annotations

import json
import sys
from pathlib import Path
import unittest
from uuid import UUID

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

HAS_API_DEPS = True
IMPORT_ERROR = ""
try:
    from fastapi.testclient import TestClient
except Exception as exc:  # noqa: BLE001
    HAS_API_DEPS = False
    IMPORT_ERROR = str(exc)

if HAS_API_DEPS:
    from sqlite_test_shims import install_sqlite_shims

    install_sqlite_shims()


class RequestLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        if not HAS_API_DEPS:
            self.skipTest(f"api test deps missing: {IMPORT_ERROR}")

        from app.main import create_app

        self.app = create_app()
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        if not HAS_API_DEPS:
            return
        self.client.close()

    def test_healthz_logs_structured_request_event(self) -> None:
        with self.assertLogs("seo_lead.api", level="INFO") as captured:
            response = self.client.get("/healthz", headers={"x-request-id": "req-123"})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("x-request-id"), "req-123")
        self.assertGreaterEqual(len(captured.output), 1)
        raw_event = captured.output[-1].split(":", 2)[-1]
        payload = json.loads(raw_event)
        self.assertEqual(payload["event"], "request")
        self.assertEqual(payload["request_id"], "req-123")
        self.assertEqual(payload["method"], "GET")
        self.assertEqual(payload["path"], "/healthz")
        self.assertEqual(payload["status_code"], 200)
        self.assertGreaterEqual(payload["duration_ms"], 0)

    def test_healthz_sets_generated_request_id_when_missing(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200, response.text)
        header = response.headers.get("x-request-id")
        self.assertIsNotNone(header)
        UUID(str(header))


if __name__ == "__main__":
    unittest.main()
