PYTHON ?= $(shell command -v python3.12 2>/dev/null || command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python3)
COMPOSE ?= docker compose
INFRA_SERVICES ?= postgres redis
ALL_SERVICES := postgres redis api worker hedger frontend caddy prover streamer

.PHONY: api worker hedger frontend caddy prover streamer all stack down test fmt local prod

api:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up --build $(INFRA_SERVICES) api

worker:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up --build $(INFRA_SERVICES) worker

stack:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up --build $(INFRA_SERVICES) api worker frontend

hedger:
	COMPOSE_PROFILES=hedger $(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up --build $(INFRA_SERVICES) hedger

frontend:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up --build $(INFRA_SERVICES) frontend

caddy:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up --build caddy

prover:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up --build prover

streamer:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up --build streamer

all:
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up --build $(ALL_SERVICES)

down:
	$(COMPOSE) down

test:
	./run_tests.sh

format:
	pre-commit run --all-files

gen-address:
	python scripts/gen_address.py --mode random --count 1

local:
	./run_local.sh

prod:
	./run_prod.sh
