#!/usr/bin/env bash
set -euo pipefail

timestamp() {
  date +"%Y-%m-%d %H:%M:%S"
}

log_step() {
  printf '\n[%s] >>> %s\n' "$(timestamp)" "$*"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export GOCACHE="${SCRIPT_DIR}/.gocache"
mkdir -p "${GOCACHE}"

log_step "Running Go tests for prover"
./check_artifacts.sh
go test "$@" -v ./...

log_step "gofmt check"
CHANGED=$(gofmt -l .)
if [ -n "$CHANGED" ]; then
  echo "gofmt would reformat:"
  echo "$CHANGED"
  exit 1
fi

log_step "go vet"
go vet -v ./...

log_step "Prover tests completed successfully"
