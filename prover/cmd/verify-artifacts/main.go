package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

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

	circuitHash := strings.TrimSpace(report.Hashes.CircuitHash)
	if circuitHash == "" {
		fmt.Println("circuit hash missing from settlement_hashes.json")
		os.Exit(1)
	}

	checkCircuitHash := func(label string, candidates []string) {
		path, err := findExistingPath(candidates)
		if err != nil {
			fmt.Printf("%s: %v\n", label, err)
			os.Exit(1)
		}
		otherHash, err := readCircuitHash(path)
		if err != nil {
			fmt.Printf("%s: %v\n", label, err)
			os.Exit(1)
		}
		if !equalHex(circuitHash, otherHash) {
			fmt.Printf("%s: circuitHash mismatch (artifacts=%s, file=%s)\n", label, circuitHash, otherHash)
			os.Exit(1)
		}
	}

	checkCircuitHash(
		"contracts/cache/settlement-vk.json",
		[]string{
			filepath.Join("..", "contracts", "cache", "settlement-vk.json"),
			filepath.Join("contracts", "cache", "settlement-vk.json"),
		},
	)
	checkCircuitHash(
		"contracts/zen/cache/settlement-vk.json",
		[]string{
			filepath.Join("..", "contracts", "zen", "cache", "settlement-vk.json"),
			filepath.Join("contracts", "zen", "cache", "settlement-vk.json"),
		},
	)

	deployPath := filepath.Join(cfg.CircuitDir, "settlement_deploy.json")
	info, err := os.Stat(deployPath)
	if err != nil || info.IsDir() || info.Size() == 0 {
		fmt.Printf("missing or unreadable: %s\n", deployPath)
		os.Exit(1)
	}
	fmt.Printf("artifacts ok (circuitHash=%s)\n", circuitHash)
	os.Exit(0)
}

type circuitHashPayload struct {
	CircuitHash string `json:"circuitHash"`
}

func readCircuitHash(path string) (string, error) {
	payload := circuitHashPayload{}
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("failed to read %s: %w", path, err)
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return "", fmt.Errorf("failed to parse %s: %w", path, err)
	}
	if strings.TrimSpace(payload.CircuitHash) == "" {
		return "", fmt.Errorf("missing circuitHash in %s", path)
	}
	return strings.TrimSpace(payload.CircuitHash), nil
}

func findExistingPath(candidates []string) (string, error) {
	for _, path := range candidates {
		info, err := os.Stat(path)
		if err == nil && !info.IsDir() {
			return path, nil
		}
	}
	return "", fmt.Errorf("missing or unreadable: %s", strings.Join(candidates, ", "))
}

func equalHex(left, right string) bool {
	normalize := func(value string) string {
		cleaned := strings.TrimSpace(strings.ToLower(value))
		if strings.HasPrefix(cleaned, "0x") {
			cleaned = cleaned[2:]
		}
		return cleaned
	}
	return normalize(left) == normalize(right)
}
