SHELL := /bin/sh

ENV_FILE := $(if $(wildcard .env),.env,.env.example)
CONTAINER_COMPOSE ?= docker compose
COMPOSE := $(CONTAINER_COMPOSE) --env-file $(ENV_FILE)

.PHONY: check compose-config db-up db-down db-logs

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
