# ---------------------------------------------------------------------
# Forge Development Shortcuts
# ---------------------------------------------------------------------
# Usage:
#   make build        → compile contracts
#   make test         → run tests with gas report
#   make full         → build + test + snapshot check + fuzz + coverage
#   make snapshot     → update .gas-snapshot baseline
#   make forgeall     → full pipeline + refresh snapshot
#   make clean        → remove build/cache artifacts
# ---------------------------------------------------------------------

# ensure bash for advanced scripting
SHELL := /usr/bin/env bash

# targets not representing actual files
.PHONY: build test full snapshot forgeall clean

build:
	@echo "🏗️  Building contracts..."
	forge build

test:
	@echo "🧪  Running tests with gas report..."
	forge test --gas-report

full:
	@echo "🚀  Running full local pipeline..."
	./run_local.sh full

snapshot:
	@echo "📊  Updating gas snapshot baseline..."
	forge snapshot

forgeall: full snapshot
	@echo "✅  All steps (build, test, fuzz, coverage, snapshot) completed."

clean:
	@echo "🧹  Cleaning build artifacts..."
	rm -rf out cache coverage
	@echo "✨  Clean workspace ready."