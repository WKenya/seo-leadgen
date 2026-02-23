# Alembic migrations

Run from repo root using worker env/deps via `uv`:

- `cd services/worker && uv run alembic -c ../../alembic.ini upgrade head`
- `cd services/worker && uv run alembic -c ../../alembic.ini revision -m "msg"`

`migrations/env.py` imports metadata from `services/worker/app/models.py`.

