FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml .
RUN uv sync --no-dev

COPY app ./app

CMD ["uv", "run", "celery", "-A", "app.worker.celery_app", "worker", "-l", "INFO"]

