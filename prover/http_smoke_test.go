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
func (s httpStubProver) IsBusy() bool        { return false }
func (s httpStubProver) Generate(_ context.Context, req settlementProofRequest) (*proofResult, error) {
	inputs, err := buildWitnessInput(req)
	if err != nil {
		return nil, err
	}
	signals := []string{
		inputs["merkleRoot"].(string),
		inputs["marketId"].(string),
		inputs["winningOutcomeId"].(string),
		inputs["totalEscrow"].(string),
		inputs["totalLiability"].(string),
		inputs["rakeBps"].(string),
		inputs["poolTotalYes"].(string),
		inputs["poolTotalNo"].(string),
		inputs["circuitHash"].(string),
		inputs["padding"].(string),
	}
	return &proofResult{
		Proof:         "{}",
		PublicSignals: signals,
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

	body := buildTestRequest()
	body.MarketID = "0x2"
	payload, _ := json.Marshal(body)
	req, err := http.NewRequest(http.MethodPost, srv.URL+"/api/v1/proofs/settlement", bytes.NewReader(payload))
	if err != nil {
		t.Fatalf("proof request failed: %v", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Prover-Secret", cfg.SharedSecret)
	proofResp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("proof request failed: %v", err)
	}
	defer proofResp.Body.Close()
	if proofResp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 from proof endpoint, got %d", proofResp.StatusCode)
	}
}
