FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    wget \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY services/worker/pyproject.toml ./pyproject.toml
RUN uv sync --no-dev
RUN uv run playwright install chromium

COPY services/worker/app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

CMD ["uv", "run", "celery", "-A", "app.worker.celery_app", "worker", "-l", "INFO"]
