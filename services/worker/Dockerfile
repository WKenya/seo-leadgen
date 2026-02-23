FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY services/worker/pyproject.toml ./pyproject.toml
RUN uv sync --no-dev

COPY services/worker/app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

CMD ["uv", "run", "celery", "-A", "app.worker.celery_app", "worker", "-l", "INFO"]
