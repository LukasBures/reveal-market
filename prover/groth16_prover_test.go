package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestReadPublicSignalsLengthMismatch(t *testing.T) {
	tmp := t.TempDir()
	path := filepath.Join(tmp, "public.json")
	if err := os.WriteFile(path, []byte(`[1,2]`), 0o644); err != nil {
		t.Fatalf("failed to write public signals: %v", err)
	}
	if _, err := readPublicSignals(path); err == nil {
		t.Fatalf("expected length mismatch error")
	}
}
