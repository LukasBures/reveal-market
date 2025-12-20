package main

import (
	"fmt"
	"os"

	"github.com/reveal-market/prover/internal/shared"
)

// Simple CLI to verify prover artifacts exist and are readable.
func main() {
	cfg := shared.LoadConfig()
	report, err := shared.VerifyArtifacts(shared.ArtifactPaths{
		WitnessScriptPath:   cfg.WitnessScriptPath,
		WasmPath:            cfg.WasmPath,
		ZKeyPath:            cfg.ZKeyPath,
		VerificationKeyPath: cfg.VerificationKeyPath,
		HashesPath:          cfg.HashesPath,
	})
	if err != nil {
		fmt.Printf("artifact verification failed: %v\n", err)
		os.Exit(1)
	}
	if len(report.Missing) > 0 {
		for _, path := range report.Missing {
			fmt.Printf("missing or unreadable: %s\n", path)
		}
		os.Exit(1)
	}
	if len(report.HashMismatches) > 0 {
		for _, mismatch := range report.HashMismatches {
			fmt.Printf("hash mismatch: %s\n", mismatch)
		}
		os.Exit(1)
	}
	if report.Hashes.CircuitHash != "" {
		fmt.Printf("artifacts ok (circuitHash=%s)\n", report.Hashes.CircuitHash)
	} else {
		fmt.Println("artifacts ok")
	}
	os.Exit(0)
}
