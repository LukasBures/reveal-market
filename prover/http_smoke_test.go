package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

type httpStubProver struct{}

func (s httpStubProver) Backend() string     { return "groth16-rapidsnark" }
func (s httpStubProver) CircuitHash() string { return "0x1" }
func (s httpStubProver) Ready() bool         { return true }
func (s httpStubProver) Generate(_ context.Context, _ settlementProofRequest) (*proofResult, error) {
	return &proofResult{
		Proof:         "{}",
		PublicSignals: []string{"1", "2", "1", "10", "9", "50", "10", "0", "1", "0"},
		ProofCalldata: [][]string{{"a"}, {"b"}},
	}, nil
}

func TestHTTPHandlersHealthAndProof(t *testing.T) {
	cfg := newTestConfig(t)
	app := newApp(cfg, httpStubProver{})
	srv := httptest.NewServer(app.routes())
	defer srv.Close()

	resp, err := http.Get(srv.URL + "/healthz")
	if err != nil {
		t.Fatalf("healthz request failed: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 from healthz, got %d", resp.StatusCode)
	}

	body := settlementProofRequest{
		MarketID:       "0x2",
		MerkleRoot:     "0x1",
		WinningOutcome: "0",
		PoolTotals:     []string{"10", "0"},
		TotalEscrow:    "10",
		TotalLiability: "9",
		RakeBps:        "50",
		CircuitHash:    "0x1",
	}
	payload, _ := json.Marshal(body)
	proofResp, err := http.Post(srv.URL+"/api/v1/proofs/settlement", "application/json", bytes.NewReader(payload))
	if err != nil {
		t.Fatalf("proof request failed: %v", err)
	}
	defer proofResp.Body.Close()
	if proofResp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 from proof endpoint, got %d", proofResp.StatusCode)
	}
}
