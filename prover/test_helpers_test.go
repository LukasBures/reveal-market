package main

import (
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/reveal-market/prover/internal/shared"
	"golang.org/x/crypto/sha3"
)

func newTestConfig(t *testing.T) shared.Config {
	t.Helper()
	temp := t.TempDir()
	witness := filepath.Join(temp, "generate_witness.js")
	wasm := filepath.Join(temp, "settlement.wasm")
	zkey := filepath.Join(temp, "settlement_final.zkey")
	vk := filepath.Join(temp, "settlement_vk.json")
	hashes := filepath.Join(temp, "settlement_hashes.json")

	writeFile(t, witness, "stub-witness")
	writeFile(t, wasm, "stub-wasm")
	writeFile(t, zkey, "stub-zkey")
	writeFile(t, vk, `{"vk":"stub"}`)

	hashPayload := shared.CircuitHashes{
		ProvingKeyHash:      hashFileKeccak(t, zkey),
		VerificationKeyHash: hashFileKeccak(t, vk),
		CircuitHash:         "0x1",
		CircuitName:         "test",
		CircuitVersion:      "0",
	}
	payload, err := json.Marshal(hashPayload)
	if err != nil {
		t.Fatalf("failed to build hash payload: %v", err)
	}
	writeFile(t, hashes, string(payload))

	return shared.Config{
		ListenAddr:          "127.0.0.1:0",
		Version:             "test",
		SharedSecret:        "secret",
		WitnessScriptPath:   witness,
		WasmPath:            wasm,
		ZKeyPath:            zkey,
		VerificationKeyPath: vk,
		HashesPath:          hashes,
		TempDir:             temp,
		ProofTimeout:        5 * time.Second,
		RequestTimeout:      5 * time.Second,
		MaxConcurrency:      1,
		ReadHeaderTimeout:   1 * time.Second,
		ReadTimeout:         1 * time.Second,
		WriteTimeout:        1 * time.Second,
		IdleTimeout:         1 * time.Second,
		MaxHeaderBytes:      1 << 20,
	}
}

func writeFile(t *testing.T, path string, payload string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(payload), 0o644); err != nil {
		t.Fatalf("failed to write %s: %v", path, err)
	}
}

func hashFileKeccak(t *testing.T, path string) string {
	t.Helper()
	file, err := os.Open(path)
	if err != nil {
		t.Fatalf("failed to open %s: %v", path, err)
	}
	defer file.Close()
	hasher := sha3.NewLegacyKeccak256()
	if _, err := io.Copy(hasher, file); err != nil {
		t.Fatalf("failed to hash %s: %v", path, err)
	}
	return "0x" + hex.EncodeToString(hasher.Sum(nil))
}
