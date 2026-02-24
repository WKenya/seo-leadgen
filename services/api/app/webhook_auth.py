from __future__ import annotations

import hashlib
import hmac
import secrets
import time


def normalize_signature(value: str) -> str:
    normalized = value.strip()
    for prefix in ("sha256=", "v1="):
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def parse_unix_timestamp(value: str | None) -> int:
    if value is None or not value.strip():
        raise ValueError("missing_webhook_timestamp")
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError("invalid_webhook_timestamp") from exc


def is_timestamp_fresh(timestamp: int, *, tolerance_seconds: int, now: int | None = None) -> bool:
    current = int(time.time()) if now is None else int(now)
    return abs(current - int(timestamp)) <= max(0, int(tolerance_seconds))


def compute_signature(*, secret: str, body: bytes, timestamp: int) -> str:
    payload = f"{timestamp}.".encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_hmac_request(
    *,
    secret: str,
    body: bytes,
    signature: str | None,
    timestamp_header: str | None,
    tolerance_seconds: int = 300,
    now: int | None = None,
) -> None:
    if not secret:
        raise ValueError("webhook_signature_secret_not_configured")
    if not signature:
        raise ValueError("missing_webhook_signature")
    timestamp = parse_unix_timestamp(timestamp_header)
    if not is_timestamp_fresh(timestamp, tolerance_seconds=tolerance_seconds, now=now):
        raise ValueError("stale_webhook_timestamp")
    expected = compute_signature(secret=secret, body=body, timestamp=timestamp)
    provided = normalize_signature(signature)
    if not secrets.compare_digest(provided, expected):
        raise ValueError("invalid_webhook_signature")
