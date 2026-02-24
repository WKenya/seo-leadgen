from __future__ import annotations

import base64
from email.message import EmailMessage

import httpx


def build_gmail_raw_message(
    *,
    sender_name: str,
    sender_email: str,
    to_email: str,
    subject: str,
    body_text: str,
) -> str:
    msg = EmailMessage()
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_text)
    raw_bytes = msg.as_bytes()
    encoded = base64.urlsafe_b64encode(raw_bytes).decode("ascii")
    return encoded.rstrip("=")


def _refresh_access_token(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> str:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        payload = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("gmail_oauth_missing_access_token")
    return token


def create_gmail_draft(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    sender_name: str,
    sender_email: str,
    to_email: str,
    subject: str,
    body_text: str,
) -> dict[str, str | None]:
    access_token = _refresh_access_token(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )
    raw = build_gmail_raw_message(
        sender_name=sender_name,
        sender_email=sender_email,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
    )
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"message": {"raw": raw}},
        )
        response.raise_for_status()
        payload = response.json()

    draft = payload.get("id")
    message = payload.get("message") or {}
    message_id = message.get("id") if isinstance(message, dict) else None
    if not isinstance(draft, str) or not draft:
        raise RuntimeError("gmail_api_missing_draft_id")

    # Best-effort UI link. Gmail may still resolve by draft/message id depending on account context.
    ui_link = f"https://mail.google.com/mail/u/0/#drafts?compose={message_id or draft}"
    return {"draft_id": draft, "message_id": message_id if isinstance(message_id, str) else None, "ui_link": ui_link}

