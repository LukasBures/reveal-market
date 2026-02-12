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
	EnableDebug         bool
	ReadHeaderTimeout   time.Duration
	ReadTimeout         time.Duration
	WriteTimeout        time.Duration
	IdleTimeout         time.Duration
	MaxHeaderBytes      int
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
	HealthCacheSeconds  int
	StrictValidation    bool
	QueueMaxDepth       int
	QueueAcquireTimeout time.Duration
	CacheTTL            time.Duration
	CacheMaxEntries     int
	AsyncQueueEnabled   bool
	WorkerMode          string
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
	readHeaderTimeout := durationEnv("PROVER_READ_HEADER_TIMEOUT_SECONDS", 5)
	readTimeout := durationEnv("PROVER_READ_TIMEOUT_SECONDS", 15)
	writeTimeout := durationEnv("PROVER_WRITE_TIMEOUT_SECONDS", 180)
	idleTimeout := durationEnv("PROVER_IDLE_TIMEOUT_SECONDS", 60)
	maxHeaderBytes := intEnv("PROVER_MAX_HEADER_BYTES", 1<<20)
	if maxHeaderBytes <= 0 {
		maxHeaderBytes = 1 << 20
	}
	conf := Config{
		ListenAddr:          getenv("PROVER_LISTEN_ADDR", "0.0.0.0:8085"),
		Version:             getenv("PROVER_VERSION", "dev"),
		ManualCircuitHash:   getenv("PROVER_CIRCUIT_HASH", ""),
		HeartbeatSeconds:    intEnv("PROVER_HEARTBEAT_SECONDS", 60),
		BackendMode:         parseBackendMode(getenv("PROVER_BACKEND", "groth16")),
		SharedSecret:        getenv("RM_PROVER_SHARED_SECRET", ""),
		EnableDebug:         boolEnv("PROVER_ENABLE_DEBUG", false),
		ReadHeaderTimeout:   readHeaderTimeout,
		ReadTimeout:         readTimeout,
		WriteTimeout:        writeTimeout,
		IdleTimeout:         idleTimeout,
		MaxHeaderBytes:      maxHeaderBytes,
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
		HealthCacheSeconds:  intEnv("PROVER_HEALTH_CACHE_SECONDS", 5),
		StrictValidation:    boolEnv("PROVER_STRICT_VALIDATION", true),
		QueueMaxDepth:       intEnv("PROVER_QUEUE_MAX_DEPTH", 32),
		QueueAcquireTimeout: durationEnv("PROVER_QUEUE_ACQUIRE_TIMEOUT_SECONDS", 2),
		CacheTTL:            durationEnv("PROVER_CACHE_TTL_SECONDS", 300),
		CacheMaxEntries:     intEnv("PROVER_CACHE_MAX_ENTRIES", 500),
		AsyncQueueEnabled:   boolEnv("PROVER_ASYNC_QUEUE_ENABLED", true),
		WorkerMode:          strings.ToLower(strings.TrimSpace(getenv("PROVER_WORKER_MODE", "inline"))),
	}
	if conf.WorkerMode == "" {
		conf.WorkerMode = "inline"
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

func boolEnv(key string, fallback bool) bool {
	value := strings.TrimSpace(strings.ToLower(getenv(key, "")))
	if value == "" {
		return fallback
	}
	switch value {
	case "1", "true", "yes", "y", "on":
		return true
	case "0", "false", "no", "n", "off":
		return false
	default:
		return fallback
	}
}

func max(a, b int) int {
	if a > b {
		return a
	}
	return b
}
