PYTHON ?= python3

.PHONY: api worker test fmt

api:
	docker compose up --build api

worker:
	docker compose up --build worker

test:
	cd backend/api && PYTHONPATH=.. $(PYTHON) -m pytest
	cd backend/worker && PYTHONPATH=.. $(PYTHON) -m pytest tests

fmt:
	pre-commit run --all-files
