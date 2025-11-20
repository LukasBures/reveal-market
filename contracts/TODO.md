# Contracts MVP Checklist

Only the items below block us from shipping contracts in an MVP.

1. **Production Groth16 rollout**
   - Finalize audited proving/verifying keys, publish their hashes on-chain, and document the rotation procedure (including `last-deployment.json` ingestion).
   - Update deployment scripts/tests to fail if circuit hashes drift from the deployed verifier.

2. **Proof replay persistence**
   - Emit/store `proofNonce` + settlement receipts so the backend (and auditors) can prove no proof was replayed or altered.
   - Wire the worker/API to surface this data under `/proofs`.

3. **Guardian/ownership operations**
   - Rehearse and document the `Ownable2Step` + guardian transfer runbooks (Factory, RakeManager, Verifier) so we can rotate keys before onboarding capital.
   - Add tests/invariants that validate the runbook steps.

Once these three deliverables land we can credibly operate the contracts for MVP-scale capital.
