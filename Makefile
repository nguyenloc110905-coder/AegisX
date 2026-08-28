SHELL := /bin/sh

ENV_FILE := $(if $(wildcard .env),.env,.env.example)
CONTAINER_COMPOSE ?= docker compose
COMPOSE := $(CONTAINER_COMPOSE) --env-file $(ENV_FILE)

UV ?= $(HOME)/.local/bin/uv

.PHONY: check compose-config db-up db-down db-logs api-sync api-test api-lint api-type api-migrate api-run agent-sync agent-test agent-lint agent-type agent-once agent-run

check:
	sh scripts/check-foundation.sh
	git diff --check
	$(COMPOSE) config --quiet

compose-config:
	$(COMPOSE) config

db-up:
	$(COMPOSE) up -d --wait postgres

db-down:
	$(COMPOSE) down

db-logs:
	$(COMPOSE) logs -f postgres

api-sync:
	$(UV) sync --project apps/api --all-groups

api-test:
	$(UV) run --project apps/api pytest apps/api/tests

api-lint:
	$(UV) run --project apps/api ruff check apps/api/src apps/api/tests

api-type:
	cd apps/api && $(UV) run mypy

api-migrate:
	$(UV) run --project apps/api alembic -c apps/api/alembic.ini upgrade head

api-run:
	cd apps/api && $(UV) run uvicorn aegisx_api.main:app --host 127.0.0.1 --port 8000 --reload

agent-sync:
	$(UV) sync --project apps/agent --all-groups

agent-test:
	$(UV) run --project apps/agent pytest apps/agent/tests

agent-lint:
	$(UV) run --project apps/agent ruff check apps/agent/src apps/agent/tests

agent-type:
	cd apps/agent && $(UV) run mypy

agent-once:
	$(UV) run --project apps/agent aegisx-agent collect-once

agent-run:
	$(UV) run --project apps/agent aegisx-agent run
