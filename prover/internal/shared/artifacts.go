package shared

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"

	"golang.org/x/crypto/sha3"
)

type ArtifactPaths struct {
	WitnessScriptPath   string
	WasmPath            string
	ZKeyPath            string
	VerificationKeyPath string
	HashesPath          string
}

type CircuitHashes struct {
	ProvingKeyHash      string `json:"provingKeyHash"`
	VerificationKeyHash string `json:"verificationKeyHash"`
	CircuitHash         string `json:"circuitHash"`
	CircuitName         string `json:"circuitName"`
	CircuitVersion      string `json:"circuitVersion"`
}

type ArtifactReport struct {
	Missing        []string
	HashMismatches []string
	Hashes         CircuitHashes
}

// CheckArtifacts ensures all required files exist, are readable, and non-empty.
func CheckArtifacts(paths []string) (bool, []string) {
	missing := make([]string, 0)
	for _, p := range paths {
		if strings.TrimSpace(p) == "" {
			missing = append(missing, "(empty path)")
			continue
		}
		info, err := os.Stat(p)
		if err != nil || info.IsDir() || info.Size() == 0 {
			missing = append(missing, p)
			continue
		}
		file, err := os.Open(p)
		if err != nil {
			missing = append(missing, p)
			continue
		}
		_ = file.Close()
	}
	return len(missing) == 0, missing
}

// VerifyArtifacts checks for required files and validates hashes against settlement_hashes.json.
func VerifyArtifacts(paths ArtifactPaths) (ArtifactReport, error) {
	required := []string{
		paths.WitnessScriptPath,
		paths.WasmPath,
		paths.ZKeyPath,
		paths.VerificationKeyPath,
		paths.HashesPath,
	}
	ok, missing := CheckArtifacts(required)
	report := ArtifactReport{Missing: missing}
	if !ok {
		return report, nil
	}

	hashes, err := loadCircuitHashes(paths.HashesPath)
	if err != nil {
		return report, err
	}
	report.Hashes = hashes

	if strings.TrimSpace(hashes.ProvingKeyHash) == "" {
		return report, fmt.Errorf("provingKeyHash missing from %s", paths.HashesPath)
	}
	if strings.TrimSpace(hashes.VerificationKeyHash) == "" {
		return report, fmt.Errorf("verificationKeyHash missing from %s", paths.HashesPath)
	}
	if strings.TrimSpace(hashes.CircuitHash) == "" {
		return report, fmt.Errorf("circuitHash missing from %s", paths.HashesPath)
	}

	provingKeyHash, err := hashFileKeccak(paths.ZKeyPath)
	if err != nil {
		return report, err
	}
	verificationKeyHash, err := hashFileKeccak(paths.VerificationKeyPath)
	if err != nil {
		return report, err
	}

	if !strings.EqualFold(normalizeHex(hashes.ProvingKeyHash), provingKeyHash) {
		report.HashMismatches = append(report.HashMismatches, fmt.Sprintf("provingKeyHash mismatch: expected %s got %s", hashes.ProvingKeyHash, provingKeyHash))
	}
	if !strings.EqualFold(normalizeHex(hashes.VerificationKeyHash), verificationKeyHash) {
		report.HashMismatches = append(report.HashMismatches, fmt.Sprintf("verificationKeyHash mismatch: expected %s got %s", hashes.VerificationKeyHash, verificationKeyHash))
	}

	return report, nil
}

func loadCircuitHashes(path string) (CircuitHashes, error) {
	file, err := os.Open(path)
	if err != nil {
		return CircuitHashes{}, fmt.Errorf("failed to read circuit hashes: %w", err)
	}
	defer file.Close()
	var hashes CircuitHashes
	if err := json.NewDecoder(file).Decode(&hashes); err != nil {
		return CircuitHashes{}, fmt.Errorf("invalid circuit hashes json: %w", err)
	}
	return hashes, nil
}

func hashFileKeccak(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", fmt.Errorf("failed to open %s: %w", path, err)
	}
	defer file.Close()
	hasher := sha3.NewLegacyKeccak256()
	buf := make([]byte, 32*1024)
	if _, err := io.CopyBuffer(hasher, file, buf); err != nil {
		return "", fmt.Errorf("failed to hash %s: %w", path, err)
	}
	return "0x" + hex.EncodeToString(hasher.Sum(nil)), nil
}

func normalizeHex(value string) string {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return ""
	}
	trimmed = strings.TrimPrefix(trimmed, "0x")
	trimmed = strings.TrimPrefix(trimmed, "0X")
	return "0x" + strings.ToLower(trimmed)
}
