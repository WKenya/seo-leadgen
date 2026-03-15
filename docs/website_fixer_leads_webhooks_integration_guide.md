# Website Fixer Lead Gen — Webhooks Integration Guide

Read when:
- wiring inbound provider webhooks (`/webhooks/outreach-events`)
- debugging webhook auth failures (`401`)
- debugging payload validation failures (`400`)
- adding/changing provider adapters

## Endpoint

- `POST /webhooks/outreach-events`

## Auth modes (evaluation order)

1. Generic HMAC mode if `WEBHOOK_SIGNATURE_SECRET` set
2. SendGrid native signature mode if `SENDGRID_WEBHOOK_PUBLIC_KEY` set and SendGrid headers present
3. Postmark native token mode if `POSTMARK_WEBHOOK_TOKEN` set and `X-Postmark-Server-Token` present
4. Mailgun native signature mode if `MAILGUN_WEBHOOK_SIGNING_KEY` set and Mailgun signature fields present
5. Shared-token fallback via `X-Webhook-Token` + `WEBHOOK_SHARED_SECRET`

Notes:
- HMAC/SendGrid/Mailgun modes enforce replay windows.
- If multiple modes are configured, precedence above controls which verifier runs.

## Replay windows

- Generic HMAC: `WEBHOOK_SIGNATURE_TOLERANCE_SECONDS` (default `300`)
- SendGrid native: `SENDGRID_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS` (default `300`)
- Mailgun native: `MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS` (default `300`)

## Accepted payload shapes

- Normalized:
  - `{"events":[{"event_type":"replied|bounced|opt_out","lead_id":"...","email_or_domain":"...","event_id":"...","payload":{...}}]}`
- SendGrid array:
  - `[{"email":"owner@example.com","event":"unsubscribe","sg_event_id":"sg-1","timestamp":1700000000}]`
- Postmark object:
  - `{"RecordType":"Bounce","MessageID":"pm-1","Email":"owner@example.com"}`
- Mailgun JSON:
  - `{"signature":{"timestamp":"...","token":"...","signature":"..."},"event-data":{"id":"mg-1","event":"unsubscribed","recipient":"owner@example.com"}}`
- Mailgun form-encoded:
  - `event-data=<json>` plus either `signature[timestamp/token/signature]` or top-level `timestamp/token/signature`
- Mailgun legacy form-encoded:
  - top-level `event`, `recipient`, optional `event-id`

## Provider event mapping

- SendGrid:
  - `bounce`, `dropped` -> `bounced`
  - `unsubscribe`, `group_unsubscribe`, `spamreport`, `spam_report` -> `opt_out`
- Postmark:
  - `Bounce` -> `bounced`
  - `SpamComplaint` -> `opt_out`
  - `SubscriptionChange` with suppress flag true-like -> `opt_out`
- Mailgun:
  - `bounced` -> `bounced`
  - `failed` + non-temporary severity -> `bounced`
  - `failed` + temporary severity -> ignored (no suppression)
  - `unsubscribed`, `complained` -> `opt_out`

## Persistence behavior

- Lead matching order: explicit `lead_id` -> `leads.email` -> `leads.website_domain` (indexed).
- Legacy fallback (`website_url`/non-canonical `website_domain`) uses normalized hostname matching with a request-scoped lookup cache to avoid repeated full-table scans.
- Optional incoming `event_id` maps to `outreach_events.external_id` (idempotency key).
- Duplicate `event_id` is skipped and counted in response `duplicates`.
- Incoming `email_or_domain` values are canonicalized before matching/persistence: emails lowercased; URL/domain forms collapsed to hostname.
- Provider value is normalized to lowercase and persisted in `outreach_events.provider` (indexed for read/metrics filters).
- Provider-adapted events store canonical metadata in `outreach_events.payload`:
  - `provider`
  - `provider_event_id`
  - `provider_event_name`
  - `provider_event_at`

## Common error details

- `invalid_webhook_token`
- `invalid_webhook_signature`
- `stale_webhook_timestamp`
- `invalid_sendgrid_signature`
- `stale_sendgrid_signature_timestamp`
- `invalid_postmark_webhook_token`
- `invalid_mailgun_signature`
- `stale_mailgun_signature_timestamp`
- `invalid_body: ...`

## Response shape

- success:
  - `{"status":"ok","processed":N,"processed_by_type":{"...":N},"processed_by_provider":{"provider":N},"duplicates":N,"rejected":[...],"rejected_by_reason":{"reason":N}}`
- rejected items include reason details (for example `invalid_event_type`, `lead_not_found`).

## Quick smoke curl (shared token mode)

```bash
curl -X POST http://localhost:8080/webhooks/outreach-events \
  -H 'X-Webhook-Token: test_shared_secret' \
  -H 'Content-Type: application/json' \
  -d '{"events":[{"event_type":"replied","email_or_domain":"owner@example.com","event_id":"evt-smoke-1"}]}'
```
