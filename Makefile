.DEFAULT_GOAL := help

ifeq ($(shell command -v docker >/dev/null 2>&1 && echo yes),yes)
COMPOSE ?= docker compose
COMPOSE_BACKEND ?= docker
else ifeq ($(shell command -v podman >/dev/null 2>&1 && echo yes),yes)
COMPOSE ?= podman compose
COMPOSE_BACKEND ?= podman
else ifeq ($(shell command -v docker-compose >/dev/null 2>&1 && echo yes),yes)
COMPOSE ?= docker-compose
COMPOSE_BACKEND ?= docker-compose
else
COMPOSE ?= docker compose
COMPOSE_BACKEND ?= none
endif

UV ?= uv
NPM ?= npm
API_TEST_PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
HAS_COMPOSE := $(shell (command -v docker >/dev/null 2>&1 || command -v podman >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1) && echo yes || echo no)

.PHONY: help doctor require-compose require-compose-engine env install install-api install-worker install-audit build up standup down restart ps logs logs-api logs-worker logs-audit logs-db migrate migrate-local revision api-dev worker-dev scheduler-dev audit-dev check test

help:
	@printf "%s\n" \
	"make env           - create .env from .env.example if missing" \
	"make doctor        - toolchain check (docker/podman, uv, npm)" \
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

doctor:
	@printf "compose runtime available: %s\n" "$(HAS_COMPOSE)"
	@printf "compose backend: %s\n" "$(COMPOSE_BACKEND)"
	@command -v docker >/dev/null 2>&1 && docker --version || true
	@command -v podman >/dev/null 2>&1 && podman --version || true
	@command -v docker-compose >/dev/null 2>&1 && docker-compose --version || true
	@command -v $(UV) >/dev/null 2>&1 && $(UV) --version || (echo "missing: $(UV)" && exit 1)
	@command -v $(NPM) >/dev/null 2>&1 && $(NPM) --version || (echo "missing: $(NPM)" && exit 1)

require-compose:
	@if [ "$(HAS_COMPOSE)" != "yes" ]; then \
		echo "missing container runtime (docker/podman/docker-compose)"; \
		echo "install Docker Desktop (or Podman)"; \
		echo "then rerun: make standup"; \
		exit 2; \
	fi

require-compose-engine: require-compose
	@if [ "$(COMPOSE_BACKEND)" = "docker" ] || [ "$(COMPOSE_BACKEND)" = "docker-compose" ]; then \
		docker info >/dev/null 2>&1 || { \
			echo "docker daemon not ready"; \
			echo "start Docker Desktop, then rerun: make standup"; \
			exit 2; \
		}; \
	fi
	@if [ "$(COMPOSE_BACKEND)" = "podman" ]; then \
		podman info >/dev/null 2>&1 || { \
			echo "podman engine not ready"; \
			echo "run: podman machine init"; \
			echo "run: podman machine start"; \
			echo "then rerun: make standup"; \
			exit 2; \
		}; \
	fi

env:
	@test -f .env || cp .env.example .env

install: install-api install-worker install-audit

install-api:
	cd services/api && $(UV) sync

install-worker:
	cd services/worker && $(UV) sync

install-audit:
	cd services/audit && $(NPM) install

build: require-compose-engine
	$(COMPOSE) build

up: require-compose-engine
	$(COMPOSE) up --build -d

standup: env up migrate

down: require-compose-engine
	$(COMPOSE) down

restart: down up

ps: require-compose-engine
	$(COMPOSE) ps

logs: require-compose-engine
	$(COMPOSE) logs -f

logs-api: require-compose-engine
	$(COMPOSE) logs -f api

logs-worker: require-compose-engine
	$(COMPOSE) logs -f worker scheduler

logs-audit: require-compose-engine
	$(COMPOSE) logs -f audit

logs-db: require-compose-engine
	$(COMPOSE) logs -f db redis

migrate: env require-compose-engine
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
	$(API_TEST_PY) -m unittest discover -s services/api/tests -p 'test_*.py' -v
	python3 -m unittest discover -s services/worker/tests -p 'test_*.py' -v
