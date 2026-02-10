package main

import (
	"expvar"
	"fmt"
	"net/http"
	"sync"
	"sync/atomic"
	"time"
)

// lightweight histogram implementation for Prometheus exposition.
type histogram struct {
	buckets []float64
	counts  []uint64
	sum     float64
	total   uint64
	mu      sync.Mutex
}

func newHistogram(bounds []float64) *histogram {
	return &histogram{
		buckets: bounds,
		counts:  make([]uint64, len(bounds)),
	}
}

func (h *histogram) Observe(value float64) {
	h.mu.Lock()
	defer h.mu.Unlock()

	h.sum += value
	h.total++
	for i, upper := range h.buckets {
		if value <= upper {
			h.counts[i]++
		}
	}
}

func (h *histogram) render(name string, w http.ResponseWriter) {
	h.mu.Lock()
	defer h.mu.Unlock()

	fmt.Fprintf(w, "# TYPE %s histogram\n", name)
	var cumulative uint64
	for i, upper := range h.buckets {
		cumulative += h.counts[i]
		fmt.Fprintf(w, "%s_bucket{le=\"%.2f\"} %d\n", name, upper, cumulative)
	}
	// +Inf bucket
	fmt.Fprintf(w, "%s_bucket{le=\"+Inf\"} %d\n", name, h.total)
	fmt.Fprintf(w, "%s_sum %f\n", name, h.sum)
	fmt.Fprintf(w, "%s_count %d\n", name, h.total)
}

var (
	proofSuccessCounter   = expvar.NewInt("prover_proofs_success_total")
	proofFailureCounter   = expvar.NewInt("prover_proofs_failure_total")
	proofCacheHitCounter  = expvar.NewInt("prover_proof_cache_hits_total")
	lastLatencyMs         = expvar.NewFloat("prover_last_proof_latency_ms")
	artifactsStatus       = expvar.NewInt("prover_artifacts_ok") // 1 when required artifacts are present
	lastInputBytes        = expvar.NewFloat("prover_last_input_bytes")
	lastTicketCount       = expvar.NewFloat("prover_last_ticket_count")
	activeProofs          atomic.Int64
	proofLatencyHistogram = newHistogram([]float64{0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 120})
)

func recordProofSuccess(duration time.Duration) {
	proofSuccessCounter.Add(1)
	lastLatencyMs.Set(float64(duration.Milliseconds()))
	proofLatencyHistogram.Observe(duration.Seconds())
}

func recordProofFailure() {
	proofFailureCounter.Add(1)
}

func recordCacheHit() {
	proofCacheHitCounter.Add(1)
}

func promMetricsHandler(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	fmt.Fprintf(w, "# TYPE prover_proofs_success_total counter\nprover_proofs_success_total %d\n", proofSuccessCounter.Value())
	fmt.Fprintf(w, "# TYPE prover_proofs_failure_total counter\nprover_proofs_failure_total %d\n", proofFailureCounter.Value())
	fmt.Fprintf(w, "# TYPE prover_proof_cache_hits_total counter\nprover_proof_cache_hits_total %d\n", proofCacheHitCounter.Value())
	fmt.Fprintf(w, "# TYPE prover_last_proof_latency_ms gauge\nprover_last_proof_latency_ms %f\n", lastLatencyMs.Value())
	fmt.Fprintf(w, "# TYPE prover_artifacts_ok gauge\nprover_artifacts_ok %d\n", artifactsStatus.Value())
	fmt.Fprintf(w, "# TYPE prover_last_input_bytes gauge\nprover_last_input_bytes %f\n", lastInputBytes.Value())
	fmt.Fprintf(w, "# TYPE prover_last_ticket_count gauge\nprover_last_ticket_count %f\n", lastTicketCount.Value())
	fmt.Fprintf(w, "# TYPE prover_active_proofs gauge\nprover_active_proofs %d\n", activeProofs.Load())
	proofLatencyHistogram.render("prover_request_latency_seconds", w)
	fmt.Fprintf(w, "# TYPE prover_up gauge\nprover_up 1\n")
}
