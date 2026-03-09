# SEO Lead (MVP scaffold)

Website fixer lead-gen system.

Current status:
- MVP pipeline scaffold + core workflow implemented
- Discovery (Google Places), audit (TLS/crawl/Lighthouse stub), drafting, Notion sync task, review/send controls

See `docs/` for product, system, and implementation design.
Release checklist: `docs/RELEASING.md`.

Python package/runtime manager:
- `uv` (API + worker)

Examples:
- `cd services/api && uv run uvicorn app.main:app --reload`
- `cd services/worker && uv run celery -A app.worker.celery_app worker -l INFO`

Note:
- `services/audit` is Node-based (Lighthouse-friendly), so it uses `npm`.

## Quick Start

Container path (Docker/Podman):
- `make doctor`
- `make standup`
- `make smoke`
- `make smoke-e2e`
- `make logs`
- optional image rebuild during smoke: `SEO_LEAD_SMOKE_BUILD=1 make smoke-e2e`
- one-command gates: `make gate-local` and `make gate-container`
  - `make gate-container` runs `standup-nobuild`, `smoke`, then `smoke-e2e`

If `make standup` says Podman engine not ready:
- `podman machine init` (first run)
- `podman machine start`
- rerun `make standup`

Local-only path (without containers; requires local Postgres/Redis):
- `make env`
- `make install`
- `make migrate-local`
- `make api-dev`
- `make worker-dev`
- `make audit-dev`

## API Endpoints (current)

Health:
- `GET /healthz`
- `GET /readyz`
- `GET /metrics/summary` (includes audits/drafts/sends/failures today, events-by-type today, webhook provider breakdown, provider/type breakdown, latest webhook providers; optional `provider` and `latest_limit` query params)

Leads / audits / issues:
- `GET /leads` (`status`, `q`, `sort`, `limit`, `offset`)
- `GET /leads/{lead_id}`
- `GET /leads/{lead_id}/audits` (`sort`, `limit`, `offset`)
- `GET /leads/{lead_id}/pipeline`
- `GET /audits/{audit_id}`
- `GET /audits/{audit_id}/issues`

Drafts / events:
- `GET /events` (`event_type`, `provider`, `sort`, `limit`, `offset`)
- `GET /drafts` (`lead_id`, `sort`, `limit`, `offset`)
- `GET /drafts/{draft_id}`
- `GET /leads/{lead_id}/drafts` (`sort`, `limit`, `offset`)
- `GET /leads/{lead_id}/events` (`event_type`, `provider`, `sort`, `limit`, `offset`)
  - event items include top-level provider fields (`provider`, `provider_event_id`, `provider_event_name`, `provider_event_at`) when present
  - paginated list responses include `count`, `total`, `has_more`, `next_offset`, `limit`, `offset`

Suppression:
- `GET /suppression` (`q`, `sort`, `limit`, `offset`)

Artifacts:
- `GET /artifacts/{path}` (optional Basic Auth via `ARTIFACTS_BASIC_AUTH_*`)

Webhooks:
- `POST /webhooks/outreach-events` (`X-Webhook-Signature` HMAC-SHA256 + `X-Webhook-Timestamp` via `WEBHOOK_SIGNATURE_SECRET`, or fallback `X-Webhook-Token` / `WEBHOOK_SHARED_SECRET`)
  - full provider setup/runbook: `docs/website_fixer_leads_webhooks_integration_guide.md`
  - supports optional per-event `event_id` for idempotent ingestion
  - HMAC payload format: `{unix_timestamp}.{raw_request_body}` (SHA-256 hex; `sha256=` prefix accepted)
  - optional Postmark native auth: `X-Postmark-Server-Token` via `POSTMARK_WEBHOOK_TOKEN`
  - optional Mailgun native auth: `signature.timestamp/token/signature` via `MAILGUN_WEBHOOK_SIGNING_KEY` (+ replay window via `MAILGUN_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS`)
  - optional SendGrid native auth: `X-Twilio-Email-Event-Webhook-Signature` + `X-Twilio-Email-Event-Webhook-Timestamp` via `SENDGRID_WEBHOOK_PUBLIC_KEY`
  - accepts normalized payload (`{"events":[...]}`), SendGrid arrays, Postmark payloads, and Mailgun `event-data` payloads (JSON + form-encoded)
  - provider-adapted events persist canonical provider metadata in `outreach_events.payload` (`provider`, provider event id/name/timestamp)
  - response includes processing breakdowns: `processed_by_type`, `processed_by_provider`, `rejected_by_reason`

Webhook setup examples (copy/paste)
- Generic shared-token mode:
  - set `WEBHOOK_SHARED_SECRET=...`
  - `curl -X POST http://localhost:8080/webhooks/outreach-events -H 'X-Webhook-Token: ...' -H 'Content-Type: application/json' -d '{"events":[{"event_type":"replied","email_or_domain":"owner@example.com","event_id":"evt-1"}]}'`
- Postmark native token mode:
  - set `POSTMARK_WEBHOOK_TOKEN=...` (and leave `WEBHOOK_SHARED_SECRET` empty if you want Postmark-only auth)
  - Postmark sends `X-Postmark-Server-Token`
  - payload example: `{"RecordType":"Bounce","MessageID":"pm-1","Email":"owner@example.com"}`
- Mailgun native signature mode:
  - set `MAILGUN_WEBHOOK_SIGNING_KEY=...`
  - JSON payload shape supported:
    - `{"signature":{"timestamp":"...","token":"...","signature":"..."},"event-data":{"id":"mg-1","event":"unsubscribed","recipient":"owner@example.com"}}`
  - form payload shape supported:
    - legacy top-level Mailgun fields (`event`, `recipient`, optional `event-id`) are accepted
    - content type `application/x-www-form-urlencoded`
    - `event-data=<json>` plus either:
      - `signature[timestamp]`, `signature[token]`, `signature[signature]`
      - or top-level `timestamp`, `token`, `signature`
- SendGrid native signature mode:
  - set `SENDGRID_WEBHOOK_PUBLIC_KEY=<PEM public key>`
  - SendGrid sends:
    - `X-Twilio-Email-Event-Webhook-Timestamp`
    - `X-Twilio-Email-Event-Webhook-Signature`
  - payload example (array):
    - `[{"email":"owner@example.com","event":"unsubscribe","sg_event_id":"sg-1"}]`

Admin triggers / review controls:
- `POST /admin/run-discovery`
- `POST /admin/run-discovery-batch`
- `POST /admin/run-audit/{lead_id}`
- `POST /admin/run-audit-batch`
- `POST /admin/run-summarize/{lead_id}/{audit_id}`
- `POST /admin/run-notion-sync/{lead_id}`
- `POST /admin/create-gmail-draft/{draft_id}`
- `POST /admin/approve-draft/{draft_id}`
- `POST /admin/send-draft/{draft_id}` (manual send stub + daily cap)
- `POST /admin/record-event/{lead_id}` (replied/bounced/opt_out/manual)
- `POST /admin/mark-optout/{lead_id}`
- `POST /admin/unsuppress/{lead_id}`

Notes:
- discovery uses Google Nearby Search when `radius_meters` > 0 (geocoded city center), then falls back to Text Search if needed
- audit checks now include basic SEO hygiene on the audited homepage (title/meta/canonical/robots noindex)
- crawl robots policy defaults to on (`CRAWL_RESPECT_ROBOTS=1`) and can be toggled if needed
- broken-link issues are aggregated by target URL/status (repeat count in issue title) to reduce noisy duplicates
- `services/audit` runs real Lighthouse if deps+Chromium are available; set `LIGHTHOUSE_STUB=1` to force stub mode
- set `PUBLIC_API_BASE_URL` so Notion `Proof` field includes clickable artifact links (screenshots/reports)
- screenshot capture uses Playwright in worker; if browser/runtime missing, audit stores a screenshot error instead of failing the whole audit
- worker Docker image now installs Playwright Chromium during build (slower/larger build, screenshot-ready)

## Tests

- `make test`
- `make smoke-e2e` (requires running Docker/Podman engine)
  - validates API read paths and audit `/run` response schema
