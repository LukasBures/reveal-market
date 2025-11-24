package main

import (
	"expvar"
	"time"
)

var (
	proofSuccessCounter = expvar.NewInt("prover_proofs_success_total")
	proofFailureCounter = expvar.NewInt("prover_proofs_failure_total")
	lastLatencyMs       = expvar.NewFloat("prover_last_proof_latency_ms")
	artifactsStatus     = expvar.NewInt("prover_artifacts_ok") // 1 when required artifacts are present
)

func recordProofSuccess(duration time.Duration) {
	proofSuccessCounter.Add(1)
	lastLatencyMs.Set(float64(duration.Milliseconds()))
}

func recordProofFailure() {
	proofFailureCounter.Add(1)
}
