package main

import (
	"expvar"
	"time"
)

var (
	proofSuccessCounter = expvar.NewInt("proover_proofs_success_total")
	proofFailureCounter = expvar.NewInt("proover_proofs_failure_total")
	lastLatencyMs       = expvar.NewFloat("proover_last_proof_latency_ms")
)

func recordProofSuccess(duration time.Duration) {
	proofSuccessCounter.Add(1)
	lastLatencyMs.Set(float64(duration.Milliseconds()))
}

func recordProofFailure() {
	proofFailureCounter.Add(1)
}
