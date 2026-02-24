from __future__ import annotations

import sys
from pathlib import Path
import unittest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.webhook_auth import compute_signature, verify_hmac_request  # noqa: E402


class WebhookAuthTests(unittest.TestCase):
    def test_verify_hmac_request_accepts_valid_signature(self) -> None:
        body = b'{"events":[]}'
        signature = compute_signature(secret="secret", body=body, timestamp=1700000000)
        verify_hmac_request(
            secret="secret",
            body=body,
            signature=f"sha256={signature}",
            timestamp_header="1700000000",
            tolerance_seconds=300,
            now=1700000100,
        )

    def test_verify_hmac_request_rejects_stale_timestamp(self) -> None:
        body = b"{}"
        signature = compute_signature(secret="secret", body=body, timestamp=1700000000)
        with self.assertRaisesRegex(ValueError, "stale_webhook_timestamp"):
            verify_hmac_request(
                secret="secret",
                body=body,
                signature=signature,
                timestamp_header="1700000000",
                tolerance_seconds=30,
                now=1700000100,
            )

    def test_verify_hmac_request_rejects_missing_timestamp(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing_webhook_timestamp"):
            verify_hmac_request(
                secret="secret",
                body=b"{}",
                signature="sha256=abc",
                timestamp_header=None,
                tolerance_seconds=300,
                now=1700000000,
            )


if __name__ == "__main__":
    unittest.main()
