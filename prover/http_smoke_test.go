package main

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/reveal-market/prover/internal/shared"
)

type httpStubProver struct{}

func (s httpStubProver) Backend() string     { return "groth16-rapidsnark" }
func (s httpStubProver) CircuitHash() string { return "0xstub" }
func (s httpStubProver) Ready() bool         { return true }
func (s httpStubProver) Generate(_ context.Context, _ settlementProofRequest) (*proofResult, error) {
	return &proofResult{
		Proof:         "{}",
		PublicSignals: []string{"1", "2", "1", "10", "9", "50", "10", "0", "1", "0"},
		ProofCalldata: [][]string{{"a"}, {"b"}},
	}, nil
}

func TestHTTPHandlersHealthAndProof(t *testing.T) {
	temp := t.TempDir()
	for _, name := range []string{"generate_witness.js", "settlement.wasm", "settlement_final.zkey"} {
		if err := os.WriteFile(filepath.Join(temp, name), []byte("stub"), 0o644); err != nil {
			t.Fatalf("failed to seed artifact %s: %v", name, err)
		}
	}

	cfg := shared.Config{
		ListenAddr:        "127.0.0.1:0",
		Version:           "test",
		HeartbeatSeconds:  1,
		BackendMode:       shared.BackendGroth16,
		NodeBinary:        "node",
		RapidSnarkBinary:  "rapidsnark",
		CircuitDir:        temp,
		WitnessScriptPath: filepath.Join(temp, "generate_witness.js"),
		WasmPath:          filepath.Join(temp, "settlement.wasm"),
		ZKeyPath:          filepath.Join(temp, "settlement_final.zkey"),
		TempDir:           temp,
		ProofTimeout:      5 * time.Second,
		MaxConcurrency:    1,
		RequestTimeout:    5 * time.Second,
	}

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
		WinningOutcome: "1",
		PoolTotals:     []string{"10", "0"},
		TotalEscrow:    "10",
		TotalLiability: "9",
		RakeBps:        "50",
		CircuitHash:    "0x1",
		Tickets: []ticketProof{{
			User:        "0x1",
			OutcomeID:   "1",
			Amount:      "10",
			Salt:        "0x1",
			TicketHash:  "0x2",
			Leaf:        "0x2",
			MerkleIndex: 0,
			MerklePath:  []string{},
		}},
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
