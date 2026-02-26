from __future__ import annotations

import base64
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


def parse_signature_header(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return (None, None)
    raw = value.strip()
    if not raw:
        return (None, None)
    if "," not in raw or "=" not in raw:
        return (None, raw)

    timestamp: str | None = None
    signature: str | None = None
    for part in raw.split(","):
        item = part.strip()
        if "=" not in item:
            continue
        key, val = item.split("=", 1)
        key = key.strip().lower()
        val = val.strip()
        if not val:
            continue
        if key == "t" and timestamp is None:
            timestamp = val
        elif key in {"v1", "sha256"} and signature is None:
            signature = val
    return (timestamp, signature)


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
    sig_timestamp, sig_value = parse_signature_header(signature)
    effective_signature = sig_value or signature
    effective_timestamp = timestamp_header or sig_timestamp
    if not effective_signature:
        raise ValueError("missing_webhook_signature")
    timestamp = parse_unix_timestamp(effective_timestamp)
    if not is_timestamp_fresh(timestamp, tolerance_seconds=tolerance_seconds, now=now):
        raise ValueError("stale_webhook_timestamp")
    expected = compute_signature(secret=secret, body=body, timestamp=timestamp)
    provided = normalize_signature(effective_signature)
    if not secrets.compare_digest(provided, expected):
        raise ValueError("invalid_webhook_signature")


def compute_mailgun_signature(*, signing_key: str, timestamp: str, token: str) -> str:
    payload = f"{timestamp}{token}".encode("utf-8")
    return hmac.new(signing_key.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_mailgun_signature(
    *,
    signing_key: str,
    timestamp: str | None,
    token: str | None,
    signature: str | None,
    tolerance_seconds: int | None = None,
    now: int | None = None,
) -> None:
    if not signing_key:
        raise ValueError("mailgun_signing_key_not_configured")
    if not timestamp or not token or not signature:
        raise ValueError("missing_mailgun_signature_fields")
    if tolerance_seconds is not None:
        ts_value = parse_unix_timestamp(str(timestamp))
        if not is_timestamp_fresh(ts_value, tolerance_seconds=tolerance_seconds, now=now):
            raise ValueError("stale_mailgun_signature_timestamp")
    expected = compute_mailgun_signature(signing_key=signing_key, timestamp=str(timestamp), token=str(token))
    if not secrets.compare_digest(str(signature).strip().lower(), expected):
        raise ValueError("invalid_mailgun_signature")


def _load_sendgrid_public_key(public_key: str):
    from cryptography.hazmat.primitives import serialization

    raw = public_key.strip()
    if not raw:
        raise ValueError("sendgrid_webhook_public_key_not_configured")
    key_bytes = raw.encode("utf-8")
    try:
        return serialization.load_pem_public_key(key_bytes)
    except Exception:  # noqa: BLE001
        try:
            der_bytes = base64.b64decode(raw)
            return serialization.load_der_public_key(der_bytes)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_sendgrid_public_key") from exc


def verify_sendgrid_signature(
    *,
    public_key: str,
    payload: bytes,
    signature_b64: str | None,
    timestamp: str | None,
    tolerance_seconds: int | None = None,
    now: int | None = None,
) -> None:
    if not public_key.strip():
        raise ValueError("sendgrid_webhook_public_key_not_configured")
    if not signature_b64 or not timestamp:
        raise ValueError("missing_sendgrid_signature_fields")
    if tolerance_seconds is not None:
        ts_value = parse_unix_timestamp(str(timestamp))
        if not is_timestamp_fresh(ts_value, tolerance_seconds=tolerance_seconds, now=now):
            raise ValueError("stale_sendgrid_signature_timestamp")
    try:
        signature = base64.b64decode(signature_b64)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid_sendgrid_signature") from exc

    verifier = _load_sendgrid_public_key(public_key)
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        verifier.verify(signature, str(timestamp).encode("utf-8") + payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise ValueError("invalid_sendgrid_signature") from exc
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid_sendgrid_signature") from exc
