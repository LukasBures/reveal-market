package main

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestGroth16ProverIntegration(t *testing.T) {
	stubDir := filepath.Join("testdata", "integration")
	nodeBin := filepath.Join(stubDir, "stub_node.sh")
	rapidBin := filepath.Join(stubDir, "stub_rapidsnark.sh")

	tempArtifacts := t.TempDir()
	witnessScript := filepath.Join(tempArtifacts, "generate_witness.js")
	wasmPath := filepath.Join(tempArtifacts, "settlement.wasm")
	zkeyPath := filepath.Join(tempArtifacts, "settlement_final.zkey")

	for _, file := range []string{witnessScript, wasmPath, zkeyPath} {
		if err := os.WriteFile(file, []byte("stub"), 0o644); err != nil {
			t.Fatalf("failed to seed artifact %s: %v", file, err)
		}
	}

	settings := groth16Settings{
		NodeBinary:        nodeBin,
		RapidSnarkBinary:  rapidBin,
		WitnessScriptPath: witnessScript,
		WasmPath:          wasmPath,
		ZKeyPath:          zkeyPath,
		TempDir:           t.TempDir(),
		Timeout:           2 * time.Second,
		MaxConcurrency:    1,
	}

	prover, err := newGroth16Prover(settings)
	if err != nil {
		t.Fatalf("failed to initialize prover: %v", err)
	}

	req := settlementProofRequest{
		MarketID:       "0x2",
		MerkleRoot:     "0x1",
		WinningOutcome: "0",
		PoolTotals:     []string{"10", "0"},
		TotalEscrow:    "10",
		TotalLiability: "9",
		RakeBps:        "50",
		CircuitHash:    "0x1",
	}

	result, err := prover.Generate(context.Background(), req)
	if err != nil {
		t.Fatalf("generate failed: %v", err)
	}
	if result.Proof == "" {
		t.Fatalf("expected proof to be populated")
	}
	expectedSignals := []string{"1", "2", "1", "10", "9", "50", "10", "0", "1", "0"}
	if len(result.PublicSignals) != len(expectedSignals) {
		t.Fatalf("expected %d public signals, got %d", len(expectedSignals), len(result.PublicSignals))
	}
	for i, value := range expectedSignals {
		if result.PublicSignals[i] != value {
			t.Fatalf("public signal %d mismatch: got %s want %s", i, result.PublicSignals[i], value)
		}
	}
	if result.ProofCalldata == nil || len(result.ProofCalldata) != 2 {
		t.Fatalf("expected calldata to contain proof + public signals")
	}
	if len(result.ProofCalldata[1]) != len(expectedSignals) {
		t.Fatalf("expected %d public signals in calldata, got %d", len(expectedSignals), len(result.ProofCalldata[1]))
	}
}
