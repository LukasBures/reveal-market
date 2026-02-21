package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func expectedSignalsForRequest(t *testing.T, req settlementProofRequest) []string {
	t.Helper()
	inputs, err := buildWitnessInput(req)
	if err != nil {
		t.Fatalf("failed to build witness input: %v", err)
	}
	keys := []string{
		"merkleRoot",
		"marketId",
		"winningOutcomeId",
		"totalEscrow",
		"totalLiability",
		"rakeBps",
		"poolTotalYes",
		"poolTotalNo",
		"circuitHash",
		"padding",
	}
	signals := make([]string, 0, len(keys))
	for _, key := range keys {
		raw, ok := inputs[key]
		if !ok {
			t.Fatalf("missing witness key: %s", key)
		}
		value, ok := raw.(string)
		if !ok {
			t.Fatalf("witness key %s has unexpected type", key)
		}
		signals = append(signals, value)
	}
	return signals
}

func TestValidateRequest(t *testing.T) {
	valid := buildTestRequest()
	if err := validateRequest(valid); err != nil {
		t.Fatalf("expected valid request, got error: %v", err)
	}

	cases := []struct {
		name   string
		modify func(req *settlementProofRequest)
	}{
		{"missing_market", func(req *settlementProofRequest) { req.MarketID = "" }},
		{"missing_root", func(req *settlementProofRequest) { req.MerkleRoot = "" }},
		{"missing_outcome", func(req *settlementProofRequest) { req.WinningOutcome = "" }},
		{"missing_total_escrow", func(req *settlementProofRequest) { req.TotalEscrow = "" }},
		{"missing_total_liability", func(req *settlementProofRequest) { req.TotalLiability = "" }},
		{"missing_rake_bps", func(req *settlementProofRequest) { req.RakeBps = "" }},
		{"bad_pool_length", func(req *settlementProofRequest) { req.PoolTotals = []string{"1"} }},
		{"missing_circuit_hash", func(req *settlementProofRequest) { req.CircuitHash = "" }},
		{"missing_batch_index", func(req *settlementProofRequest) { req.BatchIndex = "" }},
		{"missing_commitments_count", func(req *settlementProofRequest) { req.CommitmentsCount = "" }},
		{"bad_ticket_length", func(req *settlementProofRequest) { req.Tickets = req.Tickets[:1] }},
		{"duplicate_ticket_id", func(req *settlementProofRequest) { req.Tickets[1].TicketID = req.Tickets[0].TicketID }},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req := valid
			tc.modify(&req)
			if err := validateRequest(req); err == nil {
				t.Fatalf("expected error for %s", tc.name)
			}
		})
	}
}

func TestBuildWitnessInput(t *testing.T) {
	req := buildTestRequest()
	req.MerkleRoot = "0x20"
	req.PoolTotals = []string{"7", "3"}
	req.TotalLiability = "14"
	req.CircuitHash = "0xbeef"
	req.CommitmentsCount = "1"
	tickets := buildTestTickets()
	tickets[0] = ticket{
		TicketID:  "7",
		OutcomeID: "1",
		Amount:    "5",
		Payout:    "11",
		User:      "0x02",
		Salt:      "0x03",
	}
	req.Tickets = tickets
	inputs, err := buildWitnessInput(req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	expected := map[string]string{
		"merkleRoot":       "32",
		"marketId":         "2748",
		"winningOutcomeId": "0",
		"totalEscrow":      "10",
		"totalLiability":   "14",
		"rakeBps":          "50",
		"poolTotalYes":     "7",
		"poolTotalNo":      "3",
		"circuitHash":      "48879",
		"padding":          "0",
		"commitmentsCount": "1",
	}
	for key, want := range expected {
		got, ok := inputs[key].(string)
		if !ok || got != want {
			t.Fatalf("input %s mismatch: got %v want %s", key, inputs[key], want)
		}
	}
	ticketIDs, ok := inputs["ticketId"].([]string)
	if !ok {
		t.Fatalf("ticketId input missing or invalid")
	}
	if len(ticketIDs) != settlementBatchSize {
		t.Fatalf("ticketId length mismatch: got %d want %d", len(ticketIDs), settlementBatchSize)
	}
	if ticketIDs[0] != "7" {
		t.Fatalf("ticketId[0] mismatch: got %s want 7", ticketIDs[0])
	}
	users, ok := inputs["user"].([]string)
	if !ok || users[0] != "2" {
		t.Fatalf("user[0] mismatch: got %v want 2", inputs["user"])
	}
	payouts, ok := inputs["payout"].([]string)
	if !ok || payouts[0] != "11" {
		t.Fatalf("payout[0] mismatch: got %v want 11", inputs["payout"])
	}
}

func TestBuildWitnessInputAllowsZeroLiability(t *testing.T) {
	req := buildTestRequest()
	req.PoolTotals = []string{"0", "10"}
	req.TotalEscrow = "10"
	req.TotalLiability = "0"
	req.WinningOutcome = "0"
	req.CommitmentsCount = "1"
	tickets := buildTestTickets()
	tickets[0] = ticket{
		TicketID:  "1",
		OutcomeID: "1",
		Amount:    "10",
		Payout:    "10",
		User:      "0x01",
		Salt:      "0x02",
	}
	req.Tickets = tickets
	if _, err := buildWitnessInput(req); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestBuildWitnessInputErrors(t *testing.T) {
	req := buildTestRequest()
	req.PoolTotals = []string{"2", "2"}
	req.TotalEscrow = "3"
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error when pool totals exceed total escrow")
	}

	req = buildTestRequest()
	req.WinningOutcome = "2"
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error for invalid winning outcome")
	}

	req = buildTestRequest()
	req.RakeBps = "20000"
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error for rake bps overflow")
	}

	req = buildTestRequest()
	req.CommitmentsCount = "257"
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error for commitments count overflow")
	}

	req = buildTestRequest()
	req.Tickets = []ticket{}
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error for ticket length mismatch")
	}
}

func TestProofHandlerSuccess(t *testing.T) {
	payload := buildTestRequest()
	stub := &stubProver{
		backend:     "stub-backend",
		circuitHash: "0x1",
		ready:       true,
		result: &proofResult{
			Proof:         `{"pi_a":["1","2"]}`,
			PublicSignals: expectedSignalsForRequest(t, payload),
			ProofCalldata: [][]string{{"0x1"}, {"0x2"}},
			Warnings:      []string{"warn"},
		},
	}
	cfg := newTestConfig(t)
	app := newApp(cfg, stub)
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)
	app.proofHandler(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status: %d", rec.Code)
	}
	var resp settlementProofResponse
	if err := json.NewDecoder(rec.Body).Decode(&resp); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}
	if resp.Proof != stub.result.Proof {
		t.Fatalf("proof mismatch: %s", resp.Proof)
	}
	if resp.Backend != stub.backend {
		t.Fatalf("backend mismatch: %s", resp.Backend)
	}
	if stub.calls != 1 {
		t.Fatalf("expected prover call, got %d", stub.calls)
	}
	if stub.lastRequest.MarketID != payload.MarketID {
		t.Fatalf("request not forwarded")
	}
}

func TestProofHandlerRequiresSecret(t *testing.T) {
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	cfg := newTestConfig(t)
	cfg.SharedSecret = "secret"
	app := newApp(cfg, stub)
	payload := buildTestRequest()
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	app.proofHandler(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	if stub.calls != 0 {
		t.Fatalf("expected prover to be skipped on unauthorized request")
	}
}

func TestProofHandlerAcceptsSecret(t *testing.T) {
	payload := buildTestRequest()
	stub := &stubProver{
		backend:     "stub-backend",
		circuitHash: "0x1",
		ready:       true,
		result: &proofResult{
			Proof:         `{"pi_a":["1","2"]}`,
			PublicSignals: expectedSignalsForRequest(t, payload),
			ProofCalldata: [][]string{{"0x1"}, {"0x2"}},
		},
	}
	cfg := newTestConfig(t)
	cfg.SharedSecret = "secret"
	app := newApp(cfg, stub)
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", "secret")
	app.proofHandler(rec, req)
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if stub.calls != 1 {
		t.Fatalf("expected prover call, got %d", stub.calls)
	}
}

func TestProofHandlerStream(t *testing.T) {
	payload := buildTestRequest()
	stub := &stubProver{
		backend:     "stub-backend",
		circuitHash: "0x1",
		ready:       true,
		result: &proofResult{
			Proof:         `{"pi_a":["1","2"]}`,
			PublicSignals: expectedSignalsForRequest(t, payload),
			ProofCalldata: [][]string{{"0x1"}, {"0x2"}},
		},
	}
	cfg := newTestConfig(t)
	app := newApp(cfg, stub)
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement?stream=1", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

	app.proofHandler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("unexpected status: %d", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); !strings.Contains(ct, "text/event-stream") {
		t.Fatalf("unexpected content type: %s", ct)
	}
	bodyStr := rec.Body.String()
	if !strings.Contains(bodyStr, "event: accepted") {
		t.Fatalf("missing accepted event")
	}
	if !strings.Contains(bodyStr, "event: proof") {
		t.Fatalf("missing proof event")
	}
	if stub.calls != 1 {
		t.Fatalf("expected prover call, got %d", stub.calls)
	}
}

func TestProofHandlerInvalidJSON(t *testing.T) {
	cfg := newTestConfig(t)
	app := newApp(cfg, &stubProver{ready: true})
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewBufferString("{"))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)
	app.proofHandler(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestProofHandlerProverError(t *testing.T) {
	stub := &stubProver{err: newValidationError("bad payload"), ready: true}
	cfg := newTestConfig(t)
	app := newApp(cfg, stub)
	payload := buildTestRequest()
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)
	app.proofHandler(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected validation error, got %d", rec.Code)
	}
}

func TestProofHandlerCircuitHashMismatch(t *testing.T) {
	stub := &stubProver{ready: true, circuitHash: "0x2"}
	cfg := newTestConfig(t)
	rawHashes, err := os.ReadFile(cfg.HashesPath)
	if err != nil {
		t.Fatalf("failed to read hashes file: %v", err)
	}
	var hashes map[string]any
	if err := json.Unmarshal(rawHashes, &hashes); err != nil {
		t.Fatalf("failed to decode hashes file: %v", err)
	}
	hashes["circuitHash"] = "0x2"
	updatedHashes, err := json.Marshal(hashes)
	if err != nil {
		t.Fatalf("failed to marshal hashes file: %v", err)
	}
	if err := os.WriteFile(cfg.HashesPath, updatedHashes, 0o644); err != nil {
		t.Fatalf("failed to update hashes file: %v", err)
	}
	app := newApp(cfg, stub)
	payload := buildTestRequest()
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)
	app.proofHandler(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
	if stub.calls != 0 {
		t.Fatalf("expected prover to be skipped on hash mismatch")
	}
}

func TestProofHandlerUnready(t *testing.T) {
	stub := &stubProver{ready: false, circuitHash: "0x1"}
	cfg := newTestConfig(t)
	app := newApp(cfg, stub)
	payload := buildTestRequest()
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)
	app.proofHandler(rec, req)
	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("expected 503, got %d", rec.Code)
	}
	if stub.calls != 0 {
		t.Fatalf("expected prover to be skipped when unready")
	}
}

func TestProofHandlerBusy(t *testing.T) {
	stub := &stubProver{ready: true, busy: true, circuitHash: "0x1"}
	cfg := newTestConfig(t)
	app := newApp(cfg, stub)
	payload := buildTestRequest()
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)
	app.proofHandler(rec, req)
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("expected 429, got %d", rec.Code)
	}
	if stub.calls != 0 {
		t.Fatalf("expected prover to be skipped when busy")
	}
}

func TestProofHandlerStrictValidation(t *testing.T) {
	payload := buildTestRequest()
	stub := &stubProver{
		ready:       true,
		circuitHash: "0x1",
		result: &proofResult{
			Proof:         `{"pi_a":["1","2"]}`,
			PublicSignals: expectedSignalsForRequest(t, payload),
		},
	}
	cfg := newTestConfig(t)
	cfg.StrictValidation = true
	app := newApp(cfg, stub)
	payload.TotalLiability = "9"
	payload.RakeBps = "50"
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)
	app.proofHandler(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
	if stub.calls != 0 {
		t.Fatalf("expected prover to be skipped when strict validation fails")
	}
}

func TestProofHandlerRejectsMismatchedPublicSignals(t *testing.T) {
	payload := buildTestRequest()
	signals := expectedSignalsForRequest(t, payload)
	signals[1] = "999"
	stub := &stubProver{
		ready:       true,
		circuitHash: "0x1",
		result: &proofResult{
			Proof:         `{"pi_a":["1","2"]}`,
			PublicSignals: signals,
		},
	}
	cfg := newTestConfig(t)
	app := newApp(cfg, stub)
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

	app.proofHandler(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("expected 500, got %d", rec.Code)
	}
	if stub.calls != 1 {
		t.Fatalf("expected prover call, got %d", stub.calls)
	}
}

func TestPreflightHandlerRequiresSecret(t *testing.T) {
	cfg := newTestConfig(t)
	app := newApp(cfg, &stubProver{ready: true, circuitHash: "0x1"})
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/proofs/preflight", nil)

	app.preflightHandler(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
}

func TestWarmupHandlerRequiresSecret(t *testing.T) {
	cfg := newTestConfig(t)
	cfg.CircuitDir = t.TempDir()
	payload := buildTestRequest()
	raw, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal warmup request: %v", err)
	}
	warmupPath := filepath.Join(cfg.CircuitDir, warmupFileName)
	if err := os.WriteFile(warmupPath, raw, 0o644); err != nil {
		t.Fatalf("failed to write warmup payload: %v", err)
	}
	stub := &stubProver{
		ready:       true,
		circuitHash: "0x1",
		result: &proofResult{
			Proof:         `{"pi_a":["1","2"]}`,
			PublicSignals: expectedSignalsForRequest(t, payload),
		},
	}
	app := newApp(cfg, stub)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/warmup", nil)

	app.warmupHandler(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	if stub.calls != 0 {
		t.Fatalf("expected prover to be skipped on unauthorized warmup")
	}
}

func TestDebugRoutesRequireSecret(t *testing.T) {
	cfg := newTestConfig(t)
	cfg.EnableDebug = true
	app := newApp(cfg, &stubProver{ready: true, circuitHash: "0x1"})
	router := app.routes()

	unauthorized := httptest.NewRecorder()
	router.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/debug/pprof/", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", unauthorized.Code)
	}

	authorized := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/debug/pprof/", nil)
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)
	router.ServeHTTP(authorized, req)
	if authorized.Code == http.StatusUnauthorized {
		t.Fatalf("expected debug endpoint to accept authorized requests")
	}
}

func TestVerifyArtifactsDetectsCircuitHashDrift(t *testing.T) {
	cfg := newTestConfig(t)
	app := newApp(cfg, &stubProver{ready: true, circuitHash: "0x1"})

	raw, err := os.ReadFile(cfg.HashesPath)
	if err != nil {
		t.Fatalf("failed to read hashes file: %v", err)
	}
	var hashes map[string]any
	if err := json.Unmarshal(raw, &hashes); err != nil {
		t.Fatalf("failed to decode hashes file: %v", err)
	}
	hashes["circuitHash"] = "0x2"
	updated, err := json.Marshal(hashes)
	if err != nil {
		t.Fatalf("failed to marshal updated hashes file: %v", err)
	}
	if err := os.WriteFile(cfg.HashesPath, updated, 0o644); err != nil {
		t.Fatalf("failed to write updated hashes file: %v", err)
	}

	ok, missing, mismatches, _ := app.verifyArtifacts()
	if ok {
		t.Fatalf("expected artifact verification to fail on circuit hash drift")
	}
	if len(missing) != 0 {
		t.Fatalf("expected no missing artifacts, got %v", missing)
	}
	if len(mismatches) == 0 {
		t.Fatalf("expected circuit hash drift mismatch")
	}
	foundDrift := false
	for _, mismatch := range mismatches {
		if strings.Contains(mismatch, "circuit_hash_drift") {
			foundDrift = true
			break
		}
	}
	if !foundDrift {
		t.Fatalf("expected circuit hash drift mismatch, got %v", mismatches)
	}
}

type stubProver struct {
	backend     string
	circuitHash string
	ready       bool
	busy        bool
	result      *proofResult
	err         error
	calls       int
	lastRequest settlementProofRequest
}

func (s *stubProver) Backend() string {
	if s.backend == "" {
		return "stub"
	}
	return s.backend
}

func (s *stubProver) CircuitHash() string {
	if s.circuitHash == "" {
		return "0x1"
	}
	return s.circuitHash
}

func (s *stubProver) Ready() bool {
	return s.ready
}

func (s *stubProver) IsBusy() bool {
	return s.busy
}

func (s *stubProver) Generate(ctx context.Context, req settlementProofRequest) (*proofResult, error) {
	s.calls++
	s.lastRequest = req
	if s.err != nil {
		return nil, s.err
	}
	if s.result == nil {
		return &proofResult{}, nil
	}
	return s.result, nil
}
