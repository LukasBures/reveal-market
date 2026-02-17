PYTHON ?= $(shell command -v python3.12 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
COMPOSE ?= docker compose
ENV_FILE ?= .env.local
COMPOSE_ENV_FILE := $(if $(wildcard $(ENV_FILE)),--env-file $(ENV_FILE),)
INFRA_SERVICES ?= postgres redis
ALL_SERVICES := postgres redis api worker hedger frontend prover streamer

.PHONY: api worker hedger frontend caddy prover streamer all stack down test fmt local prod
.PHONY: test-backend test-api test-worker test-frontend test-hedger test-streamer test-relayer test-contracts test-contracts-polygon test-contracts-zen test-prover

api:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml $(COMPOSE_ENV_FILE) up --build $(INFRA_SERVICES) api

worker:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml $(COMPOSE_ENV_FILE) up --build $(INFRA_SERVICES) worker

stack:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml $(COMPOSE_ENV_FILE) up --build $(INFRA_SERVICES) api worker frontend

hedger:
	COMPOSE_PROFILES=hedger $(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml $(COMPOSE_ENV_FILE) up --build $(INFRA_SERVICES) hedger

frontend:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml $(COMPOSE_ENV_FILE) up --build $(INFRA_SERVICES) frontend

caddy:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml $(COMPOSE_ENV_FILE) up --build caddy

prover:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml $(COMPOSE_ENV_FILE) up --build prover

streamer:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml $(COMPOSE_ENV_FILE) up --build streamer

all:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml $(COMPOSE_ENV_FILE) up --build $(ALL_SERVICES)

down:
	$(COMPOSE) $(COMPOSE_ENV_FILE) down

test:
	./run_tests.sh

test-backend:
	./backend/run_tests.sh

test-api:
	cd backend/api && uv run --project . --extra dev pytest

test-worker:
	cd backend/worker && uv run --project . --extra dev pytest

test-frontend:
	cd frontend && ./run_tests.sh

test-hedger:
	cd hedger && ./run_tests.sh

test-streamer:
	cd streamer && ./run_tests.sh

test-relayer:
	cd relayer && ./run_tests.sh

test-contracts: test-contracts-polygon test-contracts-zen

test-contracts-polygon:
	cd contracts/polygon && ./run_tests.sh

test-contracts-zen:
	cd contracts/zen && ./run_tests.sh

test-prover:
	cd prover && ./run_tests.sh

format:
	uv run pre-commit run --all-files

gen-address:
	python scripts/gen_address.py --mode random --count 1

local:
	./run_local.sh

prod:
	./run_prod.sh
