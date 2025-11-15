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
		EventID:        "evt",
		ConditionID:    "0xabc",
		TotalPool:      "10",
		WinningPool:    "5",
		OutcomeHash:    "0x1",
		MarketAddress:  "0x2",
		Nonce:          "0x3",
		CircuitVersion: 1,
	}

	result, err := prover.Generate(context.Background(), req)
	if err != nil {
		t.Fatalf("generate failed: %v", err)
	}
	if result.Proof == "" || len(result.PublicSignals) == 0 {
		t.Fatalf("expected proof and public signals to be populated")
	}
	if result.ProofCalldata == nil || len(result.ProofCalldata) != 2 {
		t.Fatalf("expected calldata to contain proof + public signals")
	}
	if result.ProofCalldata[1][0] != "0x9" {
		t.Fatalf("unexpected calldata content: %+v", result.ProofCalldata)
	}
}
