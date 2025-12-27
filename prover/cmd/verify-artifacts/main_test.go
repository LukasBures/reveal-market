package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestReadCircuitHash(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "settlement-vk.json")
	if err := os.WriteFile(path, []byte(`{"circuitHash":"0xabc123"}`), 0o600); err != nil {
		t.Fatalf("failed to write temp file: %v", err)
	}
	got, err := readCircuitHash(path)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
	if got != "0xabc123" {
		t.Fatalf("expected circuitHash 0xabc123, got %s", got)
	}
}

func TestReadCircuitHashRejectsMissing(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "settlement-vk.json")
	if err := os.WriteFile(path, []byte(`{"circuitHash":""}`), 0o600); err != nil {
		t.Fatalf("failed to write temp file: %v", err)
	}
	if _, err := readCircuitHash(path); err == nil {
		t.Fatalf("expected error for missing circuitHash")
	}
}

func TestEqualHexNormalizesPrefixes(t *testing.T) {
	if !equalHex("0xAbC123", "abc123") {
		t.Fatalf("expected hex values to match")
	}
	if equalHex("0xabc123", "0xdef456") {
		t.Fatalf("expected hex values to differ")
	}
}
