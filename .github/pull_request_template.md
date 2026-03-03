## Summary

<!-- 1-3 sentences describing what this PR does and why -->

## Changes

-

## Type

- [ ] Feature
- [ ] Bug fix
- [ ] Refactor
- [ ] Docs
- [ ] CI/CD
- [ ] Dependencies

## Affected Services

- [ ] backend/api
- [ ] backend/worker
- [ ] backend/shared
- [ ] frontend
- [ ] streamer
- [ ] relayer
- [ ] hedger
- [ ] prover
- [ ] contracts/zen
- [ ] contracts/polygon

## Testing

<!-- How was this tested? Include commands, screenshots, or links to CI runs -->

## Security Checklist

- [ ] No new secrets committed or logged
- [ ] CSP headers updated if new external domains added (api + frontend)
- [ ] Contract changes reviewed for reentrancy / access control
- [ ] Settlement constants (BATCH_SIZE=256, MERKLE_DEPTH=8) unchanged or aligned across all services

## Deploy Notes

<!-- Anything the deployer needs to know: new env vars, migrations, manual steps -->
