# SEO Lead (MVP scaffold)

Website fixer lead-gen system.

Current status:
- Milestone 1 scaffold in progress
- FastAPI + Celery + Postgres/Redis + Node audit service layout created

See `docs/` for product, system, and implementation design.

Python package/runtime manager:
- `uv` (API + worker)

Examples:
- `cd services/api && uv run uvicorn app.main:app --reload`
- `cd services/worker && uv run celery -A app.worker.celery_app worker -l INFO`

Note:
- `services/audit` is Node-based (Lighthouse-friendly), so it uses `npm`.

