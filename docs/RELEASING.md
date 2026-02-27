# Releasing

## Scope
- MVP monorepo: `services/api`, `services/worker`, `services/audit`.
- Goal: reproducible local/container verification before tag/push.

## Preflight
1. `git status --short` is clean.
2. `.env` present and required keys set (`DATABASE_URL`, `REDIS_URL`, provider/webhook keys as needed).
3. Tooling present:
   - `make doctor`
   - `uv --version`
   - `npm --version`

## Local Gate
1. `make test`
2. `make check`

## Container Gate
1. Start engine (Docker Desktop or Podman machine).
2. `make standup`
3. `make smoke`
4. `make smoke-e2e`
5. Optional full rebuild during smoke: `SEO_LEAD_SMOKE_BUILD=1 make smoke-e2e`

If `make smoke-e2e` fails with engine-not-ready:
- Podman:
  1. `podman machine init` (first run)
  2. `podman machine start`
- Docker:
  1. Start Docker Desktop

## Release Steps
1. Confirm docs reflect behavior/API/env changes.
2. Confirm migrations applied (`make migrate` or `make migrate-local`).
3. Create release commit(s) with Conventional Commits.
4. Tag/version per project policy.
5. Push branch/tag (only when explicitly requested).

## Post-Release Checks
1. `GET /healthz`
2. `GET /readyz`
3. `GET /metrics/summary`
4. Webhook ingest sanity (`POST /webhooks/outreach-events`) in chosen auth mode.
