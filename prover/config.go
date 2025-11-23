package main

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"time"
)

type proverBackendMode string

const (
	backendAuto    proverBackendMode = "auto"
	backendMock    proverBackendMode = "mock"
	backendGroth16 proverBackendMode = "groth16"
)

// config captures every runtime setting for the prover service.
type config struct {
	ListenAddr        string
	Version           string
	ManualCircuitHash string
	HeartbeatSeconds  int
	BackendMode       proverBackendMode
	NodeBinary        string
	RapidSnarkBinary  string
	CircuitDir        string
	WitnessScriptPath string
	WasmPath          string
	ZKeyPath          string
	TempDir           string
	ProofTimeout      time.Duration
	MaxConcurrency    int
	RequestTimeout    time.Duration
	RakePercent       float64
	HaircutPercent    float64
	WorsenPercent     float64
	TotalMonetisation float64
}

// loadConfig builds the config struct from environment variables (with sane defaults).
func loadConfig() config {
	baseDir := getenv("PROVER_CIRCUIT_DIR", filepath.Join("circuits", "build"))
	conf := config{
		ListenAddr:        getenv("PROVER_LISTEN_ADDR", "0.0.0.0:8085"),
		Version:           getenv("PROVER_VERSION", "dev"),
		ManualCircuitHash: getenv("PROVER_CIRCUIT_HASH", ""),
		HeartbeatSeconds:  intEnv("PROVER_HEARTBEAT_SECONDS", 60),
		BackendMode:       parseBackendMode(getenv("PROVER_BACKEND", "groth16")),
		NodeBinary:        getenv("PROVER_NODE_BINARY", "node"),
		RapidSnarkBinary:  getenv("PROVER_RAPIDSNARK_BINARY", "rapidsnark"),
		CircuitDir:        baseDir,
		WitnessScriptPath: getenv("PROVER_WITNESS_SCRIPT", filepath.Join(baseDir, "settlement_js", "generate_witness.js")),
		WasmPath:          getenv("PROVER_WASM_PATH", filepath.Join(baseDir, "settlement_js", "settlement.wasm")),
		ZKeyPath:          getenv("PROVER_ZKEY_PATH", filepath.Join(baseDir, "settlement_final.zkey")),
		TempDir:           getenv("PROVER_TEMP_DIR", os.TempDir()),
		ProofTimeout:      durationEnv("PROVER_PROOF_TIMEOUT_SECONDS", 120),
		MaxConcurrency:    max(1, intEnv("PROVER_MAX_CONCURRENCY", runtime.NumCPU())),
		RequestTimeout:    durationEnv("PROVER_REQUEST_TIMEOUT_SECONDS", 90),
		RakePercent:       floatEnv("PROVER_RAKE_PERCENT", 0.02),
		HaircutPercent:    floatEnv("PROVER_HAIRCUT_PERCENT", 0.12),
		WorsenPercent:     floatEnv("PROVER_WORSEN_PERCENT", 0.03),
	}
	conf.TotalMonetisation = conf.RakePercent + conf.HaircutPercent + conf.WorsenPercent
	return conf
}

func parseBackendMode(raw string) proverBackendMode {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "mock":
		return backendMock
	case "groth16":
		return backendGroth16
	default:
		return backendAuto
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
