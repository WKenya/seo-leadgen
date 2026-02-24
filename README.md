# SEO Lead (MVP scaffold)

Website fixer lead-gen system.

Current status:
- MVP pipeline scaffold + core workflow implemented
- Discovery (Google Places), audit (TLS/crawl/Lighthouse stub), drafting, Notion sync task, review/send controls

See `docs/` for product, system, and implementation design.

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
- `make logs`

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
- `GET /metrics/summary`

Leads / audits / issues:
- `GET /leads`
- `GET /leads/{lead_id}`
- `GET /leads/{lead_id}/audits`
- `GET /leads/{lead_id}/pipeline`
- `GET /audits/{audit_id}`
- `GET /audits/{audit_id}/issues`

Drafts / events:
- `GET /events`
- `GET /drafts`
- `GET /drafts/{draft_id}`
- `GET /leads/{lead_id}/drafts`
- `GET /leads/{lead_id}/events`

Suppression:
- `GET /suppression`

Artifacts:
- `GET /artifacts/{path}` (optional Basic Auth via `ARTIFACTS_BASIC_AUTH_*`)

Webhooks:
- `POST /webhooks/outreach-events` (`X-Webhook-Token` header, `WEBHOOK_SHARED_SECRET`)
  - supports optional per-event `event_id` for idempotent ingestion

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
- `services/audit` runs real Lighthouse if deps+Chromium are available; set `LIGHTHOUSE_STUB=1` to force stub mode
- set `PUBLIC_API_BASE_URL` so Notion `Proof` field includes clickable artifact links (screenshots/reports)

## Tests

- `make test`
