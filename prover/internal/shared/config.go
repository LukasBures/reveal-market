package shared

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

type proverBackendMode string

const (
	BackendAuto    proverBackendMode = "auto"
	BackendMock    proverBackendMode = "mock"
	BackendGroth16 proverBackendMode = "groth16"
)

// Config captures every runtime setting for the prover service.
type Config struct {
	ListenAddr          string
	Version             string
	ManualCircuitHash   string
	HeartbeatSeconds    int
	BackendMode         proverBackendMode
	SharedSecret        string
	NodeBinary          string
	RapidSnarkBinary    string
	CircuitDir          string
	WitnessScriptPath   string
	WitnessBinaryPath   string
	WasmPath            string
	ZKeyPath            string
	VerificationKeyPath string
	HashesPath          string
	TempDir             string
	ProofTimeout        time.Duration
	MaxConcurrency      int
	RequestTimeout      time.Duration
	MaxRequestBytes     int64
}

// LoadConfig builds the config struct from environment variables (with sane defaults).
func LoadConfig() Config {
	baseDir := getenv("PROVER_CIRCUIT_DIR", filepath.Join("circuits", "build"))
	proofTimeout := durationEnv("PROVER_PROOF_TIMEOUT_SECONDS", 120)
	requestTimeout := durationEnv("PROVER_REQUEST_TIMEOUT_SECONDS", int(proofTimeout.Seconds()))
	maxRequestBytes := intEnv("PROVER_MAX_REQUEST_BYTES", 1_048_576)
	if maxRequestBytes <= 0 {
		maxRequestBytes = 1_048_576
	}
	conf := Config{
		ListenAddr:          getenv("PROVER_LISTEN_ADDR", "0.0.0.0:8085"),
		Version:             getenv("PROVER_VERSION", "dev"),
		ManualCircuitHash:   getenv("PROVER_CIRCUIT_HASH", ""),
		HeartbeatSeconds:    intEnv("PROVER_HEARTBEAT_SECONDS", 60),
		BackendMode:         parseBackendMode(getenv("PROVER_BACKEND", "groth16")),
		SharedSecret:        getenv("PROVER_SHARED_SECRET", ""),
		NodeBinary:          getenv("PROVER_NODE_BINARY", "node"),
		RapidSnarkBinary:    getenv("PROVER_RAPIDSNARK_BINARY", "rapidsnark"),
		CircuitDir:          baseDir,
		WitnessScriptPath:   getenv("PROVER_WITNESS_SCRIPT", filepath.Join(baseDir, "settlement_js", "generate_witness.js")),
		WitnessBinaryPath:   resolveWitnessBinary(baseDir),
		WasmPath:            getenv("PROVER_WASM_PATH", filepath.Join(baseDir, "settlement_js", "settlement.wasm")),
		ZKeyPath:            getenv("PROVER_ZKEY_PATH", filepath.Join(baseDir, "settlement_final.zkey")),
		VerificationKeyPath: getenv("PROVER_VK_PATH", filepath.Join(baseDir, "settlement_vk.json")),
		HashesPath:          getenv("PROVER_HASHES_PATH", filepath.Join(baseDir, "settlement_hashes.json")),
		TempDir:             getenv("PROVER_TEMP_DIR", os.TempDir()),
		ProofTimeout:        proofTimeout,
		MaxConcurrency:      max(1, intEnv("PROVER_MAX_CONCURRENCY", runtime.NumCPU())),
		RequestTimeout:      requestTimeout,
		MaxRequestBytes:     int64(maxRequestBytes),
	}
	return conf
}

func resolveWitnessBinary(baseDir string) string {
	if value := strings.TrimSpace(getenv("PROVER_WITNESS_BINARY", "")); value != "" {
		return value
	}
	mode := strings.ToLower(strings.TrimSpace(getenv("PROVER_WITNESS_MODE", "")))
	if mode == "cpp" {
		return filepath.Join(baseDir, "settlement_cpp", "settlement")
	}
	return ""
}

func parseBackendMode(raw string) proverBackendMode {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "mock":
		return BackendMock
	case "groth16":
		return BackendGroth16
	default:
		return BackendAuto
	}
}

func durationEnv(key string, defaultSeconds int) time.Duration {
	seconds := intEnv(key, defaultSeconds)
	if seconds <= 0 {
		seconds = defaultSeconds
	}
	return time.Duration(seconds) * time.Second
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
