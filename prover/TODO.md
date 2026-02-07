# Prover TODO

**MVP - Critical**
- Ensure all artifacts in `prover/circuits/build` are present and verified.
- Confirm circuit hash matches contracts and API.

**MVP - High**
- Add timeouts for proof generation and clear error reporting.

**MVP - Medium**
- Add resource limit checks for memory and CPU usage.

**MVP - Low**
- Add structured logs for proof input sizes.

**MVP - Nice to have**
- Add a dry-run validation mode for deployments.

**Production - Critical**
- Store proving keys securely and rotate safely.

**Production - High**
- Add a queueing layer to smooth proof bursts.

**Production - Medium**
- Add canary proof runs after deployments.

**Production - Low**
- Add proof cache for repeated inputs.

**Production - Nice to have**
- Add horizontal scaling with shared artifact store.
