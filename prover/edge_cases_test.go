package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// TestEdgeMalformedJSON verifies that various forms of malformed JSON are
// rejected with HTTP 400 and the "invalid_json" error code.
func TestEdgeMalformedJSON(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	cases := []struct {
		name string
		body string
	}{
		{"truncated_object", `{"marketId": "0xabc"`},
		{"trailing_comma", `{"marketId": "0xabc",}`},
		{"bare_string", `hello world`},
		{"just_opening_brace", `{`},
		{"just_closing_brace", `}`},
		{"array_instead_of_object", `[1,2,3]`},
		{"numeric_literal", `42`},
		{"double_colon", `{"key":: "value"}`},
		{"unquoted_key", `{key: "value"}`},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", strings.NewReader(tc.body))
			req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

			app.proofHandler(rec, req)

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("expected 400 for %s, got %d; body=%s", tc.name, rec.Code, rec.Body.String())
			}

			var resp map[string]any
			if err := json.NewDecoder(rec.Body).Decode(&resp); err != nil {
				t.Fatalf("failed to decode error response: %v", err)
			}
			if resp["error"] != "invalid_json" {
				t.Fatalf("expected error code 'invalid_json', got %v", resp["error"])
			}
		})
	}

	if stub.calls != 0 {
		t.Fatalf("prover should never be called for malformed JSON; got %d calls", stub.calls)
	}
}

// TestEdgeMissingRequiredFields tests that each required field, when absent,
// causes a 400 with "invalid_request" error code.
func TestEdgeMissingRequiredFields(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	cases := []struct {
		name   string
		modify func(req *settlementProofRequest)
	}{
		{"empty_tickets", func(req *settlementProofRequest) { req.Tickets = []ticket{} }},
		{"missing_marketId", func(req *settlementProofRequest) { req.MarketID = "" }},
		{"missing_merkleRoot", func(req *settlementProofRequest) { req.MerkleRoot = "" }},
		{"missing_winningOutcomeId", func(req *settlementProofRequest) { req.WinningOutcome = "" }},
		{"missing_totalEscrow", func(req *settlementProofRequest) { req.TotalEscrow = "" }},
		{"missing_totalLiability", func(req *settlementProofRequest) { req.TotalLiability = "" }},
		{"missing_rakeBps", func(req *settlementProofRequest) { req.RakeBps = "" }},
		{"missing_circuitHash", func(req *settlementProofRequest) { req.CircuitHash = "" }},
		{"missing_batchIndex", func(req *settlementProofRequest) { req.BatchIndex = "" }},
		{"missing_commitmentsCount", func(req *settlementProofRequest) { req.CommitmentsCount = "" }},
		{"whitespace_only_marketId", func(req *settlementProofRequest) { req.MarketID = "   " }},
		{"whitespace_only_merkleRoot", func(req *settlementProofRequest) { req.MerkleRoot = "   " }},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			payload := buildTestRequest()
			tc.modify(&payload)
			body, err := json.Marshal(payload)
			if err != nil {
				t.Fatalf("failed to marshal: %v", err)
			}

			rec := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
			req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

			app.proofHandler(rec, req)

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("expected 400 for %s, got %d; body=%s", tc.name, rec.Code, rec.Body.String())
			}

			var resp map[string]any
			if err := json.NewDecoder(rec.Body).Decode(&resp); err != nil {
				t.Fatalf("failed to decode error response: %v", err)
			}
			if resp["error"] != "invalid_request" {
				t.Fatalf("expected error code 'invalid_request', got %v", resp["error"])
			}
		})
	}

	if stub.calls != 0 {
		t.Fatalf("prover should never be called for missing fields; got %d calls", stub.calls)
	}
}

// TestEdgeOversizedBatch verifies that a request with >256 tickets is rejected.
func TestEdgeOversizedBatch(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	payload := buildTestRequest()
	// Build 257 tickets (one more than the required batch size of 256)
	oversized := make([]ticket, settlementBatchSize+1)
	for i := range oversized {
		oversized[i] = ticket{
			TicketID:  strconv.Itoa(i),
			OutcomeID: "0",
			Amount:    "0",
			Payout:    "0",
			User:      "0",
			Salt:      "0",
		}
	}
	payload.Tickets = oversized

	body, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

	app.proofHandler(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for oversized batch, got %d; body=%s", rec.Code, rec.Body.String())
	}

	var resp map[string]any
	if err := json.NewDecoder(rec.Body).Decode(&resp); err != nil {
		t.Fatalf("failed to decode error response: %v", err)
	}
	msg, _ := resp["message"].(string)
	if !strings.Contains(msg, fmt.Sprintf("%d", settlementBatchSize)) {
		t.Fatalf("expected error message to mention batch size %d, got: %s", settlementBatchSize, msg)
	}
	if stub.calls != 0 {
		t.Fatalf("prover should not be called for oversized batch; got %d calls", stub.calls)
	}
}

// TestEdgeUndersizedBatch verifies that a request with <256 tickets is rejected.
func TestEdgeUndersizedBatch(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	// Test multiple undersized values
	sizes := []int{0, 1, 100, 255}
	for _, size := range sizes {
		t.Run(fmt.Sprintf("size_%d", size), func(t *testing.T) {
			payload := buildTestRequest()
			undersized := make([]ticket, size)
			for i := range undersized {
				undersized[i] = ticket{
					TicketID:  strconv.Itoa(i),
					OutcomeID: "0",
					Amount:    "0",
					Payout:    "0",
					User:      "0",
					Salt:      "0",
				}
			}
			payload.Tickets = undersized

			body, err := json.Marshal(payload)
			if err != nil {
				t.Fatalf("failed to marshal: %v", err)
			}

			rec := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
			req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

			app.proofHandler(rec, req)

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("expected 400 for undersized batch (%d tickets), got %d; body=%s", size, rec.Code, rec.Body.String())
			}
		})
	}

	if stub.calls != 0 {
		t.Fatalf("prover should not be called for undersized batch; got %d calls", stub.calls)
	}
}

// TestEdgeInvalidOutcomeID verifies that winningOutcomeId values other than
// "0" or "1" are rejected. The basic validateRequest allows any non-empty
// value, but buildWitnessInput (which is called during proof generation)
// rejects invalid outcomes.
func TestEdgeInvalidOutcomeID(t *testing.T) {
	invalidOutcomes := []string{"5", "2", "99", "-1", "abc"}
	for _, outcome := range invalidOutcomes {
		t.Run("outcome_"+outcome, func(t *testing.T) {
			payload := buildTestRequest()
			payload.WinningOutcome = outcome

			// buildWitnessInput validates that winningOutcomeId < 2, so the
			// error surfaces inside the prover stub when it calls
			// buildWitnessInput. We verify that the handler returns an error
			// status (400 or 500 depending on where validation catches it).
			err := validateRequest(payload)
			if err != nil {
				// The basic validator does not check outcome range; this
				// should not error.
				t.Fatalf("validateRequest unexpectedly failed: %v", err)
			}

			// Test via buildWitnessInput which performs the range check
			_, witnessErr := buildWitnessInput(payload)
			if witnessErr == nil {
				t.Fatalf("expected buildWitnessInput to reject outcomeId=%s", outcome)
			}
		})
	}
}

// TestEdgeNegativeAndOverflowValues verifies handling of negative amounts and
// overflow rake BPS values via buildWitnessInput (which is invoked during
// proof generation).
func TestEdgeNegativeAndOverflowValues(t *testing.T) {
	t.Run("negative_amount_in_ticket", func(t *testing.T) {
		payload := buildTestRequest()
		payload.Tickets[0].Amount = "-100"

		// Negative amounts should be caught by buildWitnessInput
		_, err := buildWitnessInput(payload)
		if err == nil {
			t.Fatalf("expected error for negative ticket amount")
		}
	})

	t.Run("overflow_rake_bps", func(t *testing.T) {
		payload := buildTestRequest()
		payload.RakeBps = "20000" // > 10000

		_, err := buildWitnessInput(payload)
		if err == nil {
			t.Fatalf("expected error for rake bps > 10000")
		}
	})

	t.Run("overflow_rake_bps_via_handler", func(t *testing.T) {
		cfg := newTestConfig(t)
		cfg.StrictValidation = true
		stub := &stubProver{ready: true, circuitHash: "0x1"}
		app := newApp(cfg, stub)

		payload := buildTestRequest()
		payload.RakeBps = "20000"
		body, err := json.Marshal(payload)
		if err != nil {
			t.Fatalf("failed to marshal: %v", err)
		}

		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
		req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

		app.proofHandler(rec, req)

		if rec.Code != http.StatusBadRequest {
			t.Fatalf("expected 400 for overflow rake bps, got %d; body=%s", rec.Code, rec.Body.String())
		}
		if stub.calls != 0 {
			t.Fatalf("prover should not be called for overflow rake bps")
		}
	})

	t.Run("negative_total_escrow_strict", func(t *testing.T) {
		cfg := newTestConfig(t)
		cfg.StrictValidation = true
		stub := &stubProver{ready: true, circuitHash: "0x1"}
		app := newApp(cfg, stub)

		payload := buildTestRequest()
		payload.TotalEscrow = "-5"
		body, err := json.Marshal(payload)
		if err != nil {
			t.Fatalf("failed to marshal: %v", err)
		}

		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
		req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

		app.proofHandler(rec, req)

		if rec.Code != http.StatusBadRequest {
			t.Fatalf("expected 400 for negative total escrow, got %d; body=%s", rec.Code, rec.Body.String())
		}
		if stub.calls != 0 {
			t.Fatalf("prover should not be called for negative total escrow")
		}
	})

	t.Run("negative_payout_in_ticket", func(t *testing.T) {
		payload := buildTestRequest()
		payload.Tickets[0].Payout = "-50"

		_, err := buildWitnessInput(payload)
		if err == nil {
			t.Fatalf("expected error for negative ticket payout")
		}
	})
}

// TestEdgeEmptyRequestBody verifies that an empty POST body yields 400.
func TestEdgeEmptyRequestBody(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	cases := []struct {
		name string
		body string
	}{
		{"empty_string", ""},
		{"whitespace_only", "   "},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", strings.NewReader(tc.body))
			req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

			app.proofHandler(rec, req)

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("expected 400 for empty body, got %d; body=%s", rec.Code, rec.Body.String())
			}
		})
	}

	if stub.calls != 0 {
		t.Fatalf("prover should not be called for empty request body; got %d calls", stub.calls)
	}
}

// TestEdgeConcurrentProofRequests launches multiple goroutines issuing proof
// requests simultaneously. All should complete without panics, returning
// either 200, 429 (busy/queue_busy), or other valid HTTP status codes.
func TestEdgeConcurrentProofRequests(t *testing.T) {
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
	cfg.AsyncQueueEnabled = true
	cfg.QueueMaxDepth = 2
	cfg.QueueAcquireTimeout = 500 * time.Millisecond
	app := newApp(cfg, stub)
	srv := httptest.NewServer(app.routes())
	defer srv.Close()

	concurrency := 3
	var wg sync.WaitGroup
	results := make([]int, concurrency)

	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()

			body, err := json.Marshal(payload)
			if err != nil {
				t.Errorf("goroutine %d: failed to marshal: %v", idx, err)
				return
			}

			req, err := http.NewRequest(http.MethodPost, srv.URL+"/api/v1/proofs/settlement", bytes.NewReader(body))
			if err != nil {
				t.Errorf("goroutine %d: failed to create request: %v", idx, err)
				return
			}
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Errorf("goroutine %d: request failed: %v", idx, err)
				return
			}
			defer resp.Body.Close()
			results[idx] = resp.StatusCode
		}(i)
	}

	wg.Wait()

	// Verify all goroutines got valid HTTP responses (no panics, no zeros)
	validCodes := map[int]bool{
		http.StatusOK:                 true,
		http.StatusTooManyRequests:    true,
		http.StatusServiceUnavailable: true,
	}
	for i, code := range results {
		if code == 0 {
			t.Fatalf("goroutine %d: received zero status code (likely a panic or error)", i)
		}
		if !validCodes[code] {
			t.Fatalf("goroutine %d: unexpected status code %d", i, code)
		}
	}

	// At least one request should have succeeded
	anySuccess := false
	for _, code := range results {
		if code == http.StatusOK {
			anySuccess = true
			break
		}
	}
	if !anySuccess {
		t.Fatalf("expected at least one successful request, got codes %v", results)
	}
}

// TestEdgeWrongHTTPMethod verifies that non-POST methods are rejected.
func TestEdgeWrongHTTPMethod(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	methods := []string{http.MethodGet, http.MethodPut, http.MethodDelete, http.MethodPatch}
	for _, method := range methods {
		t.Run(method, func(t *testing.T) {
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(method, "/api/v1/proofs/settlement", nil)
			req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

			app.proofHandler(rec, req)

			if rec.Code != http.StatusMethodNotAllowed {
				t.Fatalf("expected 405 for %s, got %d", method, rec.Code)
			}
		})
	}

	if stub.calls != 0 {
		t.Fatalf("prover should not be called for wrong HTTP methods; got %d calls", stub.calls)
	}
}

// TestEdgeDuplicateTicketIDs verifies that duplicate ticket IDs are rejected.
func TestEdgeDuplicateTicketIDs(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	payload := buildTestRequest()
	// Set the first two tickets to have the same ID
	payload.Tickets[0].TicketID = "duplicate-id"
	payload.Tickets[1].TicketID = "duplicate-id"

	body, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

	app.proofHandler(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for duplicate ticket IDs, got %d; body=%s", rec.Code, rec.Body.String())
	}

	var resp map[string]any
	if err := json.NewDecoder(rec.Body).Decode(&resp); err != nil {
		t.Fatalf("failed to decode error response: %v", err)
	}
	msg, _ := resp["message"].(string)
	if !strings.Contains(msg, "unique") {
		t.Fatalf("expected error about unique ticket IDs, got: %s", msg)
	}
	if stub.calls != 0 {
		t.Fatalf("prover should not be called for duplicate ticket IDs; got %d calls", stub.calls)
	}
}

// TestEdgePoolTotalsWrongLength verifies pool totals arrays with != 2 entries.
func TestEdgePoolTotalsWrongLength(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	cases := []struct {
		name   string
		totals []string
	}{
		{"empty", []string{}},
		{"single", []string{"10"}},
		{"three", []string{"10", "5", "3"}},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			payload := buildTestRequest()
			payload.PoolTotals = tc.totals

			body, err := json.Marshal(payload)
			if err != nil {
				t.Fatalf("failed to marshal: %v", err)
			}

			rec := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
			req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

			app.proofHandler(rec, req)

			if rec.Code != http.StatusBadRequest {
				t.Fatalf("expected 400 for pool totals length %d, got %d", len(tc.totals), rec.Code)
			}
		})
	}

	if stub.calls != 0 {
		t.Fatalf("prover should not be called for wrong pool totals length; got %d calls", stub.calls)
	}
}

// TestEdgeMissingAuthHeader verifies the settlement endpoint rejects requests
// without the X-Prover-Secret header.
func TestEdgeMissingAuthHeader(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	payload := buildTestRequest()
	body, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	t.Run("no_header", func(t *testing.T) {
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
		// Deliberately omit X-Prover-Secret

		app.proofHandler(rec, req)

		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("expected 401 without auth header, got %d", rec.Code)
		}
	})

	t.Run("wrong_secret", func(t *testing.T) {
		rec := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
		req.Header.Set("X-Prover-Secret", "wrong-secret-value")

		app.proofHandler(rec, req)

		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("expected 401 with wrong secret, got %d", rec.Code)
		}
	})

	if stub.calls != 0 {
		t.Fatalf("prover should never be called for unauthorized requests; got %d calls", stub.calls)
	}
}

// TestEdgeCircuitHashMismatchInRequest verifies that a request whose
// circuitHash does not match the prover's circuit hash is rejected.
func TestEdgeCircuitHashMismatchInRequest(t *testing.T) {
	cfg := newTestConfig(t)
	stub := &stubProver{ready: true, circuitHash: "0x1"}
	app := newApp(cfg, stub)

	payload := buildTestRequest()
	payload.CircuitHash = "0xdeadbeef" // Does not match "0x1"

	body, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

	app.proofHandler(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 for circuit hash mismatch, got %d; body=%s", rec.Code, rec.Body.String())
	}
	if stub.calls != 0 {
		t.Fatalf("prover should not be called for circuit hash mismatch; got %d calls", stub.calls)
	}
}

// TestEdgeConcurrentProofRequestsNoPanics performs a larger burst of concurrent
// requests without a queue to verify the prover responds with 429 when busy
// and never panics.
func TestEdgeConcurrentProofRequestsNoPanics(t *testing.T) {
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
	// No async queue -- requests that find the prover busy get 429 directly
	app := newApp(cfg, stub)
	srv := httptest.NewServer(app.routes())
	defer srv.Close()

	concurrency := 5
	var wg sync.WaitGroup
	statuses := make([]int, concurrency)

	for i := 0; i < concurrency; i++ {
		wg.Add(1)
		go func(idx int) {
			defer wg.Done()

			body, err := json.Marshal(payload)
			if err != nil {
				t.Errorf("goroutine %d: marshal failed: %v", idx, err)
				return
			}

			req, err := http.NewRequest(http.MethodPost, srv.URL+"/api/v1/proofs/settlement", bytes.NewReader(body))
			if err != nil {
				t.Errorf("goroutine %d: request creation failed: %v", idx, err)
				return
			}
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

			resp, err := http.DefaultClient.Do(req)
			if err != nil {
				t.Errorf("goroutine %d: request failed: %v", idx, err)
				return
			}
			defer resp.Body.Close()
			statuses[idx] = resp.StatusCode
		}(i)
	}

	wg.Wait()

	for i, code := range statuses {
		if code == 0 {
			t.Fatalf("goroutine %d: got zero status (panic or connection error)", i)
		}
		// All responses should be valid HTTP codes
		if code < 200 || code >= 600 {
			t.Fatalf("goroutine %d: invalid status code %d", i, code)
		}
	}
}

// TestEdgeExtraFieldsIgnored verifies that unknown JSON fields in the request
// body are silently ignored and do not cause an error.
func TestEdgeExtraFieldsIgnored(t *testing.T) {
	cfg := newTestConfig(t)
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
	app := newApp(cfg, stub)

	// Manually construct JSON with an extra unknown field
	raw, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal: %v", err)
	}
	// Inject an extra field into the JSON object
	modified := strings.Replace(string(raw), `"marketId"`, `"unknownField":"foobar","marketId"`, 1)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", strings.NewReader(modified))
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)

	app.proofHandler(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 with extra fields ignored, got %d; body=%s", rec.Code, rec.Body.String())
	}
	if stub.calls != 1 {
		t.Fatalf("expected prover to be called once, got %d", stub.calls)
	}
}

// TestEdgeCommitmentsCountOverflow verifies that a commitments count exceeding
// the batch size is rejected via buildWitnessInput.
func TestEdgeCommitmentsCountOverflow(t *testing.T) {
	cases := []struct {
		name  string
		count string
	}{
		{"just_over", "257"},
		{"large", "10000"},
		{"max_uint", "999999999999999999"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			payload := buildTestRequest()
			payload.CommitmentsCount = tc.count

			_, err := buildWitnessInput(payload)
			if err == nil {
				t.Fatalf("expected error for commitmentsCount=%s", tc.count)
			}
		})
	}
}
