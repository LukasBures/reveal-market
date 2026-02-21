package shared

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestVerifyArtifactsIncludesWitnessAssets(t *testing.T) {
	temp := t.TempDir()
	witness := filepath.Join(temp, "generate_witness.js")
	wasm := filepath.Join(temp, "settlement.wasm")
	zkey := filepath.Join(temp, "settlement_final.zkey")
	vk := filepath.Join(temp, "settlement_vk.json")
	hashes := filepath.Join(temp, "settlement_hashes.json")

	writeArtifact(t, witness, "witness-script")
	writeArtifact(t, wasm, "wasm")
	writeArtifact(t, zkey, "zkey")
	writeArtifact(t, vk, `{"vk":"stub"}`)

	payload := CircuitHashes{
		WitnessScriptHash:   mustHash(t, witness),
		WasmHash:            mustHash(t, wasm),
		ProvingKeyHash:      mustHash(t, zkey),
		VerificationKeyHash: mustHash(t, vk),
		CircuitHash:         "0x1",
	}
	writeHashes(t, hashes, payload)

	report, err := VerifyArtifacts(ArtifactPaths{
		WitnessScriptPath:   witness,
		WasmPath:            wasm,
		ZKeyPath:            zkey,
		VerificationKeyPath: vk,
		HashesPath:          hashes,
	})
	if err != nil {
		t.Fatalf("verify failed: %v", err)
	}
	if len(report.Missing) > 0 {
		t.Fatalf("unexpected missing artifacts: %v", report.Missing)
	}
	if len(report.HashMismatches) > 0 {
		t.Fatalf("unexpected hash mismatches: %v", report.HashMismatches)
	}
}

func TestVerifyArtifactsRequiresWitnessHashes(t *testing.T) {
	temp := t.TempDir()
	witness := filepath.Join(temp, "generate_witness.js")
	wasm := filepath.Join(temp, "settlement.wasm")
	zkey := filepath.Join(temp, "settlement_final.zkey")
	vk := filepath.Join(temp, "settlement_vk.json")
	hashes := filepath.Join(temp, "settlement_hashes.json")

	writeArtifact(t, witness, "witness-script")
	writeArtifact(t, wasm, "wasm")
	writeArtifact(t, zkey, "zkey")
	writeArtifact(t, vk, `{"vk":"stub"}`)

	payload := CircuitHashes{
		ProvingKeyHash:      mustHash(t, zkey),
		VerificationKeyHash: mustHash(t, vk),
		CircuitHash:         "0x1",
	}
	writeHashes(t, hashes, payload)

	_, err := VerifyArtifacts(ArtifactPaths{
		WitnessScriptPath:   witness,
		WasmPath:            wasm,
		ZKeyPath:            zkey,
		VerificationKeyPath: vk,
		HashesPath:          hashes,
	})
	if err == nil {
		t.Fatalf("expected witness hash validation error")
	}
}

func writeArtifact(t *testing.T, path string, data string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(data), 0o644); err != nil {
		t.Fatalf("failed to write %s: %v", path, err)
	}
}

func writeHashes(t *testing.T, path string, payload CircuitHashes) {
	t.Helper()
	raw, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("failed to marshal hashes payload: %v", err)
	}
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatalf("failed to write %s: %v", path, err)
	}
}

func mustHash(t *testing.T, path string) string {
	t.Helper()
	hash, err := hashFileKeccak(path)
	if err != nil {
		t.Fatalf("failed to hash %s: %v", path, err)
	}
	return hash
}
