PYTHON ?= $(shell command -v python3.13 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
COMPOSE ?= docker compose
INFRA_SERVICES ?= postgres redis

.PHONY: api worker stack down test fmt

api:
	$(COMPOSE) up --build $(INFRA_SERVICES) api

worker:
	$(COMPOSE) up --build $(INFRA_SERVICES) worker

stack:
	$(COMPOSE) up --build $(INFRA_SERVICES) api worker frontend

down:
	$(COMPOSE) down

test:
	./backend/run_tests.sh

fmt:
	pre-commit run --all-files
