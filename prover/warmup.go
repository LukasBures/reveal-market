package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"

	"github.com/reveal-market/prover/internal/shared"
)

const warmupFileName = "warmup_request.json"

func loadWarmupRequest(cfg shared.Config) (settlementProofRequest, error) {
	baseDir := cfg.CircuitDir
	path := filepath.Join(baseDir, warmupFileName)
	raw, err := os.ReadFile(path)
	if err != nil {
		return settlementProofRequest{}, fmt.Errorf("warmup file missing: %s", path)
	}
	var req settlementProofRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		return settlementProofRequest{}, fmt.Errorf("warmup file invalid: %w", err)
	}
	if err := validateRequest(req); err != nil {
		return settlementProofRequest{}, err
	}
	if cfg.StrictValidation {
		if err := validateStrictRequest(req); err != nil {
			return settlementProofRequest{}, err
		}
	}
	return req, nil
}
