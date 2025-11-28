package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/reveal-market/prover/internal/shared"
)

func TestValidateRequest(t *testing.T) {
	valid := settlementProofRequest{
		MarketID:       "0xabc",
		MerkleRoot:     "0x01",
		WinningOutcome: "0",
		PoolTotals:     []string{"10", "0"},
		TotalEscrow:    "10",
		TotalLiability: "5",
		PayoutMulWad:   "500000000000000000",
		RakeBps:        "100",
		CircuitHash:    "0xdead",
		Tickets: []ticketProof{{
			User:        "0x1",
			OutcomeID:   "1",
			Amount:      "10",
			Salt:        "0x1",
			TicketHash:  "0x2",
			Leaf:        "0x2",
			MerklePath:  []string{},
			MerkleIndex: 0,
		}},
	}
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
		{"missing_payout_multiplier", func(req *settlementProofRequest) { req.PayoutMulWad = "" }},
		{"missing_rake_bps", func(req *settlementProofRequest) { req.RakeBps = "" }},
		{"bad_pool_length", func(req *settlementProofRequest) { req.PoolTotals = []string{"1"} }},
		{"missing_tickets", func(req *settlementProofRequest) { req.Tickets = nil }},
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
	req := settlementProofRequest{
		MarketID:       "0xabc",
		MerkleRoot:     "0x20",
		WinningOutcome: "0",
		PoolTotals:     []string{"7", "3"},
		TotalEscrow:    "10",
		TotalLiability: "14",
		PayoutMulWad:   "2000000000000000000",
		RakeBps:        "50",
		CircuitHash:    "0xbeef",
		Tickets: []ticketProof{{
			User:        "0x1",
			OutcomeID:   "1",
			Amount:      "10",
			Salt:        "0x1",
			TicketHash:  "0x2",
			Leaf:        "0x2",
			MerklePath:  []string{},
			MerkleIndex: 0,
		}},
	}
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
	}
	for key, want := range expected {
		if got := inputs[key]; got != want {
			t.Fatalf("input %s mismatch: got %s want %s", key, got, want)
		}
	}
}

func TestBuildWitnessInputErrors(t *testing.T) {
	req := settlementProofRequest{
		MarketID:       "1",
		MerkleRoot:     "0x1",
		WinningOutcome: "1",
		PoolTotals:     []string{"2", "2"},
		TotalEscrow:    "3",
		TotalLiability: "10",
		PayoutMulWad:   "2000000000000000000",
		RakeBps:        "10",
		CircuitHash:    "0x1",
		Tickets: []ticketProof{{
			User:        "0x1",
			OutcomeID:   "1",
			Amount:      "10",
			Salt:        "0x1",
			TicketHash:  "0x2",
			Leaf:        "0x2",
			MerklePath:  []string{},
			MerkleIndex: 0,
		}},
	}
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error when pool totals do not match total escrow")
	}

	req.WinningOutcome = "2"
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error for invalid winning outcome")
	}

	req = settlementProofRequest{
		MarketID:       "1",
		MerkleRoot:     "0x1",
		WinningOutcome: "0",
		PoolTotals:     []string{"7", "3"},
		TotalEscrow:    "10",
		TotalLiability: "10", // wrong: winningPool (7) * 2e18 / 1e18 = 14
		PayoutMulWad:   "2000000000000000000",
		RakeBps:        "10",
		CircuitHash:    "0x1",
		Tickets: []ticketProof{{
			User:        "0x1",
			OutcomeID:   "1",
			Amount:      "10",
			Salt:        "0x1",
			TicketHash:  "0x2",
			Leaf:        "0x2",
			MerklePath:  []string{},
			MerkleIndex: 0,
		}},
	}
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error when liability mismatches payout multiplier")
	}
}

func TestProofHandlerSuccess(t *testing.T) {
	stub := &stubProver{
		backend:     "stub-backend",
		circuitHash: "0xtest",
		ready:       true,
		result: &proofResult{
			Proof:         `{"pi_a":["1","2"]}`,
			PublicSignals: []string{"1", "2", "3", "4", "5", "6", "7", "8", "9", "0"},
			ProofCalldata: [][]string{{"0x1"}, {"0x2"}},
			Warnings:      []string{"warn"},
		},
	}
	app := newApp(shared.Config{Version: "test", RequestTimeout: time.Second}, stub)
	payload := settlementProofRequest{
		MarketID:       "0xabc",
		MerkleRoot:     "0x1",
		WinningOutcome: "0",
		PoolTotals:     []string{"10", "0"},
		TotalEscrow:    "10",
		TotalLiability: "9",
		PayoutMulWad:   "900000000000000000",
		RakeBps:        "50",
		CircuitHash:    "0x1",
		Tickets: []ticketProof{{
			User:        "0x1",
			OutcomeID:   "1",
			Amount:      "10",
			Salt:        "0x1",
			TicketHash:  "0x2",
			Leaf:        "0x2",
			MerklePath:  []string{},
			MerkleIndex: 0,
		}},
	}
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
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

func TestProofHandlerInvalidJSON(t *testing.T) {
	app := newApp(shared.Config{Version: "test", RequestTimeout: time.Second}, &stubProver{ready: true})
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewBufferString("{"))
	app.proofHandler(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestProofHandlerProverError(t *testing.T) {
	stub := &stubProver{err: newValidationError("bad payload"), ready: true}
	app := newApp(shared.Config{Version: "test", RequestTimeout: time.Second}, stub)
	payload := settlementProofRequest{
		MarketID:       "0xabc",
		MerkleRoot:     "0x1",
		WinningOutcome: "0",
		PoolTotals:     []string{"10", "0"},
		TotalEscrow:    "10",
		TotalLiability: "9",
		PayoutMulWad:   "900000000000000000",
		RakeBps:        "50",
		CircuitHash:    "0x1",
		Tickets:        []ticketProof{{User: "0x1", OutcomeID: "1", Amount: "10", Salt: "0x1", TicketHash: "0x2", Leaf: "0x2", MerkleIndex: 0}},
	}
	body, _ := json.Marshal(payload)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewReader(body))
	app.proofHandler(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected validation error, got %d", rec.Code)
	}
}

type stubProver struct {
	backend     string
	circuitHash string
	ready       bool
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
		return "0xstub"
	}
	return s.circuitHash
}

func (s *stubProver) Ready() bool {
	return s.ready
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
