#!/usr/bin/env bash
set -euo pipefail

# Clean up any inherited --localstorage-file flags (not allowed in NODE_OPTIONS) to avoid Node warnings.
EXISTING_NODE_OPTIONS="${NODE_OPTIONS:-}"
if [[ -n "${EXISTING_NODE_OPTIONS}" ]]; then
  CLEANED_NODE_OPTIONS="${EXISTING_NODE_OPTIONS//--localstorage-file[^ ]*/}"
  if [[ -n "${CLEANED_NODE_OPTIONS// /}" ]]; then
    export NODE_OPTIONS="${CLEANED_NODE_OPTIONS}"
  else
    unset NODE_OPTIONS
  fi
fi

next build
