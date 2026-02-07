# Relayer TODO

**MVP - Critical**
- (done) Confirm relayer auth (bearer token or IP allowlist) is enforced in prod.
- (done) Validate internal API secrets are set and reachable.

**MVP - High**
- Add exponential backoff for status polling and relayer API retries.

**MVP - Medium**
- Add structured error reason aggregation for job failures.

**MVP - Low**
- Improve queue stats and admin endpoints.

**MVP - Nice to have**
- (done) Add per-route rate limit controls.

**Production - Critical**
- Ensure key management and signing isolation for relayer private key.

**Production - High**
- Add circuit breaker for RPC errors.

**Production - Medium**
- Add chain head lag metrics.

**Production - Low**
- Add transaction fee bump heuristics visibility.

**Production - Nice to have**
- Add multi-relayer HA mode.
