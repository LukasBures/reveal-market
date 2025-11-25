package main

import (
	"fmt"
	"os"

	"github.com/reveal-market/prover/internal/shared"
)

// Simple CLI to verify prover artifacts exist and are readable.
func main() {
	cfg := shared.LoadConfig()
	paths := []string{cfg.WitnessScriptPath, cfg.WasmPath, cfg.ZKeyPath}
	ok, missing := shared.CheckArtifacts(paths)
	if ok {
		fmt.Println("artifacts ok")
		os.Exit(0)
	}
	for _, path := range missing {
		fmt.Printf("missing or unreadable: %s\n", path)
	}
	os.Exit(1)
}
