.DEFAULT_GOAL := help

ifeq ($(shell command -v docker >/dev/null 2>&1 && echo yes),yes)
COMPOSE ?= docker compose
else ifeq ($(shell command -v podman >/dev/null 2>&1 && echo yes),yes)
COMPOSE ?= podman compose
else ifeq ($(shell command -v docker-compose >/dev/null 2>&1 && echo yes),yes)
COMPOSE ?= docker-compose
else
COMPOSE ?= docker compose
endif

UV ?= uv
NPM ?= npm

.PHONY: help env install install-api install-worker install-audit build up standup down restart ps logs logs-api logs-worker logs-audit logs-db migrate migrate-local revision api-dev worker-dev scheduler-dev audit-dev check test

help:
	@printf "%s\n" \
	"make env           - create .env from .env.example if missing" \
	"make install       - install local dev deps (uv + npm)" \
	"make build         - docker compose build" \
	"make up            - start full docker stack in background" \
	"make standup       - env + up + migrate (one-command bring-up)" \
	"make down          - stop docker stack" \
	"make logs          - tail all container logs" \
	"make migrate       - run alembic migrations in worker container" \
	"make migrate-local - run alembic migrations locally via uv" \
	"make api-dev       - run api locally (uv)" \
	"make worker-dev    - run worker locally (uv)" \
	"make scheduler-dev - run celery beat locally (uv)" \
	"make audit-dev     - run audit service locally (npm)" \
	"make test          - run unit tests (stdlib unittest)"

env:
	@test -f .env || cp .env.example .env

install: install-api install-worker install-audit

install-api:
	cd services/api && $(UV) sync

install-worker:
	cd services/worker && $(UV) sync

install-audit:
	cd services/audit && $(NPM) install

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up --build -d

standup: env up migrate

down:
	$(COMPOSE) down

restart: down up

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

logs-api:
	$(COMPOSE) logs -f api

logs-worker:
	$(COMPOSE) logs -f worker scheduler

logs-audit:
	$(COMPOSE) logs -f audit

logs-db:
	$(COMPOSE) logs -f db redis

migrate: env
	$(COMPOSE) exec -T worker uv run alembic -c /app/alembic.ini upgrade head

migrate-local: env
	cd services/worker && $(UV) run alembic -c ../../alembic.ini upgrade head

revision:
	@test -n "$(name)" || (echo 'usage: make revision name="message"'; exit 1)
	cd services/worker && $(UV) run alembic -c ../../alembic.ini revision -m "$(name)"

api-dev: env
	cd services/api && $(UV) run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

worker-dev: env
	cd services/worker && $(UV) run celery -A app.worker.celery_app worker -l INFO

scheduler-dev: env
	cd services/worker && $(UV) run celery -A app.worker.celery_app beat -l INFO

audit-dev:
	cd services/audit && $(NPM) start

check:
	python3 -m compileall services/api/app services/worker/app migrations

test:
	python3 -m unittest discover -s services/worker/tests -p 'test_*.py' -v
