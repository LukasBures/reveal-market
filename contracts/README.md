# Contracts Monorepo

This directory now namespaces chain-specific workspaces:

- `zen/` – Reveal Market contracts targeting the Horizen/ZEN appchain (Foundry workspace with `src/`, `test/`, `script/`, `lib/`, docs, cache, run scripts, etc.).
- `polygon/` – Polygon hedging LP vault (self-contained Foundry workspace with its own `lib/`, `src/`, `test/`, and run scripts).

Notes
- CI/build tooling runs each workspace separately (see `.github/workflows/cicd.yml` and `contracts/run_tests.sh`).
- Keep deployment artifacts (verifying keys, last deploy JSON) scoped per chain under their respective workspace.
- Shared patterns (e.g., Verifier, MarketFactory) can be duplicated per chain; avoid cross-chain remappings.
