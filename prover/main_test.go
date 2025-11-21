package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestValidateRequest(t *testing.T) {
	valid := settlementProofRequest{
		EventID:        "evt",
		ConditionID:    "0xabc",
		TotalPool:      "10",
		WinningPool:    "5",
		OutcomeHash:    "0x01",
		MarketAddress:  "0xabc",
		Nonce:          "123",
		CircuitVersion: 1,
	}
	if err := validateRequest(valid); err != nil {
		t.Fatalf("expected valid request, got error: %v", err)
	}

	cases := []struct {
		name   string
		modify func(req *settlementProofRequest)
	}{
		{"missing_event", func(req *settlementProofRequest) { req.EventID = "" }},
		{"missing_condition", func(req *settlementProofRequest) { req.ConditionID = "   " }},
		{"missing_total_pool", func(req *settlementProofRequest) { req.TotalPool = "" }},
		{"missing_winning_pool", func(req *settlementProofRequest) { req.WinningPool = "" }},
		{"missing_nonce", func(req *settlementProofRequest) { req.Nonce = "" }},
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
		EventID:        "evt",
		ConditionID:    "0xabc",
		TotalPool:      "10",
		WinningPool:    "5",
		OutcomeHash:    "0x20",
		MarketAddress:  "0xabc",
		Nonce:          "0x2a",
		CircuitVersion: 1,
	}
	inputs, err := buildWitnessInput(req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	expected := map[string]string{
		"totalPool":      "10",
		"winningPool":    "5",
		"outcomeHash":    "32",
		"circuitVersion": "1",
		"nonce":          "42",
		"marketAddress":  "2748",
	}
	for key, want := range expected {
		if got := inputs[key]; got != want {
			t.Fatalf("input %s mismatch: got %s want %s", key, got, want)
		}
	}
}

func TestBuildWitnessInputErrors(t *testing.T) {
	req := settlementProofRequest{
		EventID:        "evt",
		ConditionID:    "0xabc",
		TotalPool:      "5",
		WinningPool:    "10",
		OutcomeHash:    "0x1",
		MarketAddress:  "0x1",
		Nonce:          "1",
		CircuitVersion: 1,
	}
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error when winning pool exceeds total pool")
	}
}

func TestProofHandlerSuccess(t *testing.T) {
    stub := &stubProver{
        backend:     "stub-backend",
        circuitHash:  "0xtest",
        ready:        true,
        result: &proofResult{
            Proof:         `{"pi_a":["1","2"]}`,
            PublicSignals: []string{"1", "2"},
            ProofCalldata: [][]string{{"0x1"}, {"0x2"}},
            Warnings:      []string{"warn"},
        },
    }
    app := newApp(config{Version: "test", RequestTimeout: time.Second}, stub)
    payload := settlementProofRequest{
        EventID:        "evt",
        ConditionID:    "0xabc",
        TotalPool:      "10",
        WinningPool:    "5",
        OutcomeHash:    "0x1",
        MarketAddress:  "0x2",
        Nonce:          "9",
        CircuitVersion: 1,
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
    if stub.lastRequest.EventID != payload.EventID {
        t.Fatalf("request not forwarded")
    }
}

func TestProofHandlerInvalidJSON(t *testing.T) {
    app := newApp(config{Version: "test", RequestTimeout: time.Second}, &stubProver{ready: true})
    rec := httptest.NewRecorder()
    req := httptest.NewRequest(http.MethodPost, "/api/v1/proofs/settlement", bytes.NewBufferString("{"))
    app.proofHandler(rec, req)
    if rec.Code != http.StatusBadRequest {
        t.Fatalf("expected 400, got %d", rec.Code)
    }
}

func TestProofHandlerProverError(t *testing.T) {
    stub := &stubProver{err: newValidationError("bad payload"), ready: true}
    app := newApp(config{Version: "test", RequestTimeout: time.Second}, stub)
    payload := settlementProofRequest{EventID: "evt", ConditionID: "0xabc", TotalPool: "10", WinningPool: "5", OutcomeHash: "0x1", MarketAddress: "0x2", Nonce: "1", CircuitVersion: 1}
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
