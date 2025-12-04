PYTHONPATH ?= src
export PYTHONPATH
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

.PHONY: setup test run fmt lint typecheck

setup:
	uv sync --group dev

test:
	uv run pytest

typecheck:
	uv run mypy --config-file ../pyproject.toml src/relayer

lint:
	uv run ruff check .
	$(MAKE) typecheck

run:
	uv run uvicorn relayer.main:app --reload --host ${RELAYER_HOST:-127.0.0.1} --port ${RELAYER_PORT:-8088}

fmt:
	uv run ruff format .
