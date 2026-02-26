from __future__ import annotations

import sys
from pathlib import Path
import unittest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.webhook_auth import (  # noqa: E402
    compute_mailgun_signature,
    compute_signature,
    parse_signature_header,
    verify_sendgrid_signature,
    verify_hmac_request,
    verify_mailgun_signature,
)


class WebhookAuthTests(unittest.TestCase):
    def test_parse_signature_header_supports_composite_format(self) -> None:
        timestamp, signature = parse_signature_header("t=1700000000, v1=abc123")
        self.assertEqual(timestamp, "1700000000")
        self.assertEqual(signature, "abc123")

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

    def test_verify_hmac_request_accepts_composite_signature_header_without_timestamp_header(self) -> None:
        body = b'{"events":[]}'
        signature = compute_signature(secret="secret", body=body, timestamp=1700000000)
        verify_hmac_request(
            secret="secret",
            body=body,
            signature=f"t=1700000000,v1={signature}",
            timestamp_header=None,
            tolerance_seconds=300,
            now=1700000001,
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

    def test_verify_mailgun_signature_accepts_valid_values(self) -> None:
        sig = compute_mailgun_signature(signing_key="mg-key", timestamp="1700", token="abc")
        verify_mailgun_signature(signing_key="mg-key", timestamp="1700", token="abc", signature=sig)

    def test_verify_mailgun_signature_rejects_invalid_signature(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_mailgun_signature"):
            verify_mailgun_signature(signing_key="mg-key", timestamp="1700", token="abc", signature="bad")

    def test_verify_mailgun_signature_rejects_stale_timestamp(self) -> None:
        sig = compute_mailgun_signature(signing_key="mg-key", timestamp="1700000000", token="abc")
        with self.assertRaisesRegex(ValueError, "stale_mailgun_signature_timestamp"):
            verify_mailgun_signature(
                signing_key="mg-key",
                timestamp="1700000000",
                token="abc",
                signature=sig,
                tolerance_seconds=30,
                now=1700000100,
            )

    def test_verify_sendgrid_signature_accepts_valid_signature(self) -> None:
        import base64

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        payload = b'[{"event":"bounce"}]'
        timestamp = "1700000000"
        sig = private_key.sign(timestamp.encode("utf-8") + payload, ec.ECDSA(hashes.SHA256()))
        verify_sendgrid_signature(
            public_key=public_key_pem,
            payload=payload,
            signature_b64=base64.b64encode(sig).decode("ascii"),
            timestamp=timestamp,
            tolerance_seconds=300,
            now=1700000001,
        )

    def test_verify_sendgrid_signature_rejects_stale_timestamp(self) -> None:
        import base64

        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        payload = b"[]"
        timestamp = "1700000000"
        sig = private_key.sign(timestamp.encode("utf-8") + payload, ec.ECDSA(hashes.SHA256()))
        with self.assertRaisesRegex(ValueError, "stale_sendgrid_signature_timestamp"):
            verify_sendgrid_signature(
                public_key=public_key_pem,
                payload=payload,
                signature_b64=base64.b64encode(sig).decode("ascii"),
                timestamp=timestamp,
                tolerance_seconds=30,
                now=1700000100,
            )


if __name__ == "__main__":
    unittest.main()
