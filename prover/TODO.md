# Prover TODO

**MVP - Critical**
- Ensure circuit artifacts in `prover/circuits/build` match the deployed contracts (hashes + version).
- Lock down internal endpoints (`/debug/pprof/*`, `/metrics/expvar`) to trusted networks or `PROVER_ENABLE_DEBUG`.
- Validate proof requests from the worker with `PROVER_SHARED_SECRET` set in prod.

**MVP - High**

**MVP - Medium**

**MVP - Low**

**MVP - Nice to have**
- Add structured logging to include proof input sizes and queue wait times.

**Production - Critical**
- Store proving keys in a secure store (KMS + sealed artifact distribution).
- Implement key rotation procedure with rollback safeguards.

**Production - High**
- Add autoscaling based on active proof concurrency and queue depth.
- Add a shared artifact cache for multi-instance deployments.

**Production - Medium**
- Add canary proofs on deploys; block traffic if canary fails.

**Production - Low**

**Production - Nice to have**
