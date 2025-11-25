package main

import (
	"expvar"
	"fmt"
	"net/http"
	"sync/atomic"
	"time"
)

var (
	proofSuccessCounter = expvar.NewInt("prover_proofs_success_total")
	proofFailureCounter = expvar.NewInt("prover_proofs_failure_total")
	lastLatencyMs       = expvar.NewFloat("prover_last_proof_latency_ms")
	artifactsStatus     = expvar.NewInt("prover_artifacts_ok") // 1 when required artifacts are present
	activeProofs        atomic.Int64
)

func recordProofSuccess(duration time.Duration) {
	proofSuccessCounter.Add(1)
	lastLatencyMs.Set(float64(duration.Milliseconds()))
	activeProofs.Add(-1)
}

func recordProofFailure() {
	proofFailureCounter.Add(1)
	activeProofs.Add(-1)
}

func promMetricsHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	fmt.Fprintf(w, "# TYPE prover_proofs_success_total counter\nprover_proofs_success_total %d\n", proofSuccessCounter.Value())
	fmt.Fprintf(w, "# TYPE prover_proofs_failure_total counter\nprover_proofs_failure_total %d\n", proofFailureCounter.Value())
	fmt.Fprintf(w, "# TYPE prover_last_proof_latency_ms gauge\nprover_last_proof_latency_ms %f\n", lastLatencyMs.Value())
	fmt.Fprintf(w, "# TYPE prover_artifacts_ok gauge\nprover_artifacts_ok %d\n", artifactsStatus.Value())
	fmt.Fprintf(w, "# TYPE prover_active_proofs gauge\nprover_active_proofs %d\n", activeProofs.Load())
	fmt.Fprintf(w, "# TYPE prover_up gauge\nprover_up 1\n")
}
