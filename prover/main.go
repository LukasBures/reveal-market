package main

import (
	"context"
	"encoding/json"
	"errors"
	"expvar"
	"fmt"
	"log"
	"net/http"
	"net/http/pprof"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/reveal-market/prover/internal/shared"
)

const defaultLogLevel = "INFO"

var (
	logLevelName  string
	logLevelValue int
)

func init() {
	log.SetFlags(0)
	logLevelName, logLevelValue = resolveLogLevel()
}

type settlementProofRequest struct {
	MarketID       string   `json:"marketId"`
	MerkleRoot     string   `json:"merkleRoot"`
	WinningOutcome string   `json:"winningOutcomeId"`
	PoolTotals     []string `json:"poolTotals"`
	TotalEscrow    string   `json:"totalEscrow"`
	TotalLiability string   `json:"totalLiability"`
	RakeBps        string   `json:"rakeBps"`
	CircuitHash    string   `json:"circuitHash"`
}

// settlementProofResponse is returned to callers after Groth16 generation.
type settlementProofResponse struct {
	Proof         string     `json:"proof"`
	PublicSignals []string   `json:"public_signals"`
	CircuitHash   string     `json:"circuit_hash"`
	GeneratedAt   string     `json:"generated_at"`
	ProverVersion string     `json:"prover_version"`
	RequestID     string     `json:"request_id"`
	Backend       string     `json:"backend"`
	ProofCalldata [][]string `json:"proof_calldata,omitempty"`
	Warnings      []string   `json:"warnings,omitempty"`
}

// proofResult is the internal representation returned by a proverEngine.
type proofResult struct {
	Proof         string
	PublicSignals []string
	ProofCalldata [][]string
	Warnings      []string
}

// app bundles configuration, prover backend, and simple state for /healthz.
type app struct {
	cfg            shared.Config
	prover         proverEngine
	startedAt      time.Time
	lastHeartbeat  atomic.Value
	lastProofAt    atomic.Value
	circuitHash    string
	requestCounter atomic.Uint64
	artifactPaths  []string
}

func newApp(cfg shared.Config, prover proverEngine) *app {
	a := &app{
		cfg:       cfg,
		prover:    prover,
		startedAt: time.Now().UTC(),
		artifactPaths: []string{
			cfg.WitnessScriptPath,
			cfg.WasmPath,
			cfg.ZKeyPath,
		},
	}
	a.lastHeartbeat.Store(time.Now().UTC())
	a.lastProofAt.Store(time.Time{})

	circuitHash := strings.TrimSpace(cfg.ManualCircuitHash)
	if backendHash := strings.TrimSpace(prover.CircuitHash()); backendHash != "" {
		circuitHash = backendHash
	}
	if circuitHash == "" {
		circuitHash = "0x0"
	}
	a.circuitHash = circuitHash
	return a
}

func (a *app) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", a.healthHandler)
	mux.HandleFunc("/heartbeat", a.heartbeatHandler)
	mux.HandleFunc("/api/v1/proofs/settlement", a.proofHandler)
	mux.HandleFunc("/metrics", promMetricsHandler)
	mux.Handle("/metrics/expvar", expvar.Handler())
	mux.HandleFunc("/debug/pprof/", pprof.Index)
	mux.HandleFunc("/debug/pprof/cmdline", pprof.Cmdline)
	mux.HandleFunc("/debug/pprof/profile", pprof.Profile)
	mux.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
	mux.HandleFunc("/debug/pprof/trace", pprof.Trace)
	return mux
}

func main() {
	cfg := shared.LoadConfig()
	logLine("info", "logging.init", map[string]any{
		"log_level":      logLevelName,
		"log_level_env":  strings.TrimSpace(strings.ToUpper(os.Getenv("PROVER_LOG_LEVEL"))),
		"service":        "prover",
		"version":        cfg.Version,
		"listen_addr":    cfg.ListenAddr,
		"heartbeat_secs": cfg.HeartbeatSeconds,
	})
	requireArtifactsOrExit(cfg)
	prover := initProver(cfg)
	server := newApp(cfg, prover)

	go server.heartbeatLoop()

	logLine("info", "prover.start", map[string]any{
		"listen_addr": cfg.ListenAddr,
		"backend":     prover.Backend(),
		"version":     cfg.Version,
		"circuit":     server.circuitHash,
	})

	if err := http.ListenAndServe(cfg.ListenAddr, server.routes()); err != nil {
		logLine("error", "prover.shutdown", map[string]any{"error": err.Error()})
		os.Exit(1)
	}
}

// initProver chooses and initializes the requested backend. Only Groth16 is supported.
func initProver(cfg shared.Config) proverEngine {
	settings := groth16Settings{
		NodeBinary:        cfg.NodeBinary,
		RapidSnarkBinary:  cfg.RapidSnarkBinary,
		WitnessScriptPath: cfg.WitnessScriptPath,
		WasmPath:          cfg.WasmPath,
		ZKeyPath:          cfg.ZKeyPath,
		TempDir:           cfg.TempDir,
		Timeout:           cfg.ProofTimeout,
		MaxConcurrency:    cfg.MaxConcurrency,
	}
	settings.CircuitHashOverride = cfg.ManualCircuitHash

	switch cfg.BackendMode {
	case shared.BackendMock:
		log.Fatalf("mock backend is disabled; provide Groth16 artifacts instead")
	case shared.BackendGroth16, shared.BackendAuto:
		prover, err := newGroth16Prover(settings)
		if err != nil {
			log.Fatalf("failed to initialize groth16 prover: %v", err)
		}
		return prover
	default:
		log.Fatalf("unknown prover backend: %s", cfg.BackendMode)
	}
	return nil
}

func (a *app) heartbeatLoop() {
	ticker := time.NewTicker(time.Duration(max(1, a.cfg.HeartbeatSeconds)) * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		now := time.Now().UTC()
		a.lastHeartbeat.Store(now)
		logLine("info", "prover.heartbeat", map[string]any{
			"timestamp": formatMillis(now),
			"backend":   a.prover.Backend(),
		})
	}
}

func (a *app) healthHandler(w http.ResponseWriter, r *http.Request) {
	lastHeartbeat, _ := a.lastHeartbeat.Load().(time.Time)
	lastProof, _ := a.lastProofAt.Load().(time.Time)
	artifactsOk, missing := checkArtifacts(a.artifactPaths)
	if artifactsOk {
		artifactsStatus.Set(1)
	} else {
		artifactsStatus.Set(0)
	}
	payload := map[string]any{
		"status":            "ok",
		"backend":           a.prover.Backend(),
		"version":           a.cfg.Version,
		"circuit_hash":      a.circuitHash,
		"uptime_seconds":    int(time.Since(a.startedAt).Seconds()),
		"last_heartbeat":    formatMillis(lastHeartbeat),
		"last_proof_at":     formatMillis(lastProof),
		"max_concurrency":   a.cfg.MaxConcurrency,
		"ready":             a.prover.Ready(),
		"artifacts_ok":      artifactsOk,
		"missing_artifacts": missing,
	}
	if !artifactsOk {
		payload["status"] = "degraded"
	}
	writeJSON(w, http.StatusOK, payload)
}

func (a *app) heartbeatHandler(w http.ResponseWriter, r *http.Request) {
	payload := map[string]any{
		"status":       "ok",
		"heartbeat_at": formatMillis(time.Now().UTC()),
	}
	writeJSON(w, http.StatusOK, payload)
}

func formatMillis(t time.Time) string {
	if t.IsZero() {
		return ""
	}
	return t.UTC().Format("2006-01-02T15:04:05.000Z")
}

func checkArtifacts(paths []string) (bool, []string) {
	return shared.CheckArtifacts(paths)
}

func requireArtifactsOrExit(cfg shared.Config) {
	ok, missing := shared.CheckArtifacts([]string{cfg.WitnessScriptPath, cfg.WasmPath, cfg.ZKeyPath})
	if ok {
		artifactsStatus.Set(1)
		return
	}
	logLine("error", "prover.artifacts.missing", map[string]any{
		"missing": missing,
	})
	os.Exit(1)
}

func (a *app) proofHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method not allowed", nil)
		return
	}
	defer r.Body.Close()

	var req settlementProofRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json", "invalid json payload", err)
		return
	}
	if err := validateRequest(req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_request", err.Error(), err)
		return
	}

	resp, err := a.generateProofResponse(r.Context(), req)
	if err != nil {
		var perr *proverError
		if errors.As(err, &perr) {
			writeError(w, perr.status, perr.code, perr.err.Error(), perr.err)
			return
		}
		writeError(w, http.StatusInternalServerError, "prover_error", "failed to generate proof", err)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

func (a *app) generateProofResponse(ctx context.Context, req settlementProofRequest) (settlementProofResponse, error) {
	requestID := a.nextRequestID()
	ctx, cancel := context.WithTimeout(ctx, a.cfg.RequestTimeout)
	defer cancel()
	start := time.Now().UTC()
	activeProofs.Add(1)
	defer activeProofs.Add(-1)

	logLine("info", "prover.request.accepted", map[string]any{
		"market_id":   req.MarketID,
		"merkle_root": req.MerkleRoot,
		"request_id":  requestID,
		"backend":     a.prover.Backend(),
	})

	result, err := a.prover.Generate(ctx, req)
	if err != nil {
		recordProofFailure()
		logLine("error", "prover.request.failed", map[string]any{
			"market_id":   req.MarketID,
			"merkle_root": req.MerkleRoot,
			"error":       err.Error(),
			"request_id":  requestID,
		})
		return settlementProofResponse{}, err
	}
	if len(result.PublicSignals) != 10 {
		recordProofFailure()
		return settlementProofResponse{}, newInternalError(fmt.Errorf("unexpected public signal count: got %d, expected 10", len(result.PublicSignals)))
	}
	now := time.Now().UTC()
	a.lastProofAt.Store(now)

	logFields := map[string]any{
		"market_id":   req.MarketID,
		"merkle_root": req.MerkleRoot,
		"request_id":  requestID,
		"backend":     a.prover.Backend(),
		"duration_ms": time.Since(start).Milliseconds(),
		"proof_size":  len(result.Proof),
		"warnings":    len(result.Warnings),
	}
	if len(result.Warnings) > 0 {
		logFields["warning_messages"] = result.Warnings
	}
	logLine("info", "prover.request.succeeded", logFields)
	recordProofSuccess(time.Since(start))

	return settlementProofResponse{
		Proof:         result.Proof,
		PublicSignals: result.PublicSignals,
		CircuitHash:   a.circuitHash,
		GeneratedAt:   formatMillis(now),
		ProverVersion: a.cfg.Version,
		RequestID:     requestID,
		Backend:       a.prover.Backend(),
		ProofCalldata: result.ProofCalldata,
		Warnings:      result.Warnings,
	}, nil
}

func (a *app) nextRequestID() string {
	counter := a.requestCounter.Add(1)
	return fmt.Sprintf("req-%d", counter)
}

type proverEngine interface {
	Backend() string
	CircuitHash() string
	Ready() bool
	Generate(ctx context.Context, req settlementProofRequest) (*proofResult, error)
}

func validateRequest(req settlementProofRequest) error {
	switch {
	case strings.TrimSpace(req.MarketID) == "":
		return errors.New("marketId required")
	case strings.TrimSpace(req.MerkleRoot) == "":
		return errors.New("merkleRoot required")
	case strings.TrimSpace(req.WinningOutcome) == "":
		return errors.New("winningOutcomeId required")
	case strings.TrimSpace(req.TotalEscrow) == "":
		return errors.New("totalEscrow required")
	case strings.TrimSpace(req.TotalLiability) == "":
		return errors.New("totalLiability required")
	case strings.TrimSpace(req.RakeBps) == "":
		return errors.New("rakeBps required")
	case len(req.PoolTotals) != 2:
		return errors.New("poolTotals must contain two entries (YES and NO)")
	case strings.TrimSpace(req.CircuitHash) == "":
		return errors.New("circuitHash required")
	default:
		return nil
	}
}

type proverError struct {
	status int
	code   string
	err    error
}

func (e *proverError) Error() string {
	return e.err.Error()
}

func newValidationError(message string) *proverError {
	return &proverError{
		status: http.StatusBadRequest,
		code:   "invalid_request",
		err:    errors.New(message),
	}
}

func newInternalError(err error) *proverError {
	return &proverError{
		status: http.StatusInternalServerError,
		code:   "prover_error",
		err:    err,
	}
}

func resolveLogLevel() (string, int) {
	raw := strings.TrimSpace(strings.ToUpper(os.Getenv("PROVER_LOG_LEVEL")))
	if raw == "" {
		raw = defaultLogLevel
	}
	value := levelValue(raw)
	if value == 0 {
		raw = defaultLogLevel
		value = levelValue(raw)
	}
	return raw, value
}

func levelValue(level string) int {
	switch strings.ToUpper(strings.TrimSpace(level)) {
	case "DEBUG":
		return 10
	case "INFO":
		return 20
	case "WARN", "WARNING":
		return 30
	case "ERROR":
		return 40
	default:
		return 0
	}
}

func shouldLog(level string) bool {
	lvl := levelValue(level)
	if lvl == 0 {
		lvl = levelValue(defaultLogLevel)
	}
	return lvl >= logLevelValue
}

func logLine(level, event string, fields map[string]any) {
	if !shouldLog(level) {
		return
	}
	payloadFields := make(map[string]any)
	if fields != nil {
		for key, value := range fields {
			payloadFields[key] = value
		}
	}
	if _, ok := payloadFields["service"]; !ok {
		payloadFields["service"] = "prover"
	}
	requestID := "-"
	if val, ok := payloadFields["request_id"]; ok {
		if s, ok := val.(string); ok && s != "" {
			requestID = s
		}
		delete(payloadFields, "request_id")
	}
	if _, ok := payloadFields["event"]; !ok {
		payloadFields["event"] = event
	} else {
		event = fmt.Sprintf("%v", payloadFields["event"])
	}
	payload, _ := json.Marshal(payloadFields)
	_, file, line, ok := runtime.Caller(2)
	location := "-"
	if ok {
		location = fmt.Sprintf("%s:%d", filepath.Base(file), line)
	}
	log.Printf(
		"%s | %s | prover | %s | %s | %s | %s",
		formatMillis(time.Now().UTC()),
		strings.ToUpper(level),
		location,
		event,
		requestID,
		payload,
	)
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		logLine("error", "prover.encode_failed", map[string]any{"error": err.Error()})
	}
}

func writeError(w http.ResponseWriter, status int, code string, message string, err error) {
	if err != nil {
		logLine("warn", "prover.response.error", map[string]any{
			"code":   code,
			"error":  err.Error(),
			"status": status,
		})
	}
	payload := map[string]any{
		"error":   code,
		"message": message,
	}
	writeJSON(w, status, payload)
}

func getenv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func intEnv(key string, fallback int) int {
	value := getenv(key, "")
	if value == "" {
		return fallback
	}
	n, err := strconv.Atoi(value)
	if err != nil {
		logLine("warn", "prover.invalid_env", map[string]any{"key": key, "value": value, "fallback": fallback})
		return fallback
	}
	if n <= 0 {
		return fallback
	}
	return n
}

func floatEnv(key string, fallback float64) float64 {
	value := getenv(key, "")
	if value == "" {
		return fallback
	}
	n, err := strconv.ParseFloat(value, 64)
	if err != nil || n < 0 {
		logLine("warn", "prover.invalid_env", map[string]any{"key": key, "value": value, "fallback": fallback})
		return fallback
	}
	return n
}
