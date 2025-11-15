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
)

func init() {
	log.SetFlags(0)
}

// settlementProofRequest mirrors backend/worker's payload.
type settlementProofRequest struct {
	EventID        string            `json:"event_id"`
	ConditionID    string            `json:"condition_id"`
	TotalPool      string            `json:"total_pool"`
	WinningPool    string            `json:"winning_pool"`
	OutcomeHash    string            `json:"outcome_hash"`
	MarketAddress  string            `json:"market_address"`
	Nonce          string            `json:"nonce"`
	CircuitVersion int               `json:"circuit_version"`
	Metadata       map[string]string `json:"metadata"`
}

// settlementProofResponse is returned to callers after Groth16 generation.
type settlementProofResponse struct {
	Proof          string      `json:"proof"`
	PublicSignals  []string    `json:"public_signals"`
	CircuitHash    string      `json:"circuit_hash"`
	GeneratedAt    time.Time   `json:"generated_at"`
	ProverVersion  string      `json:"prover_version"`
	RequestNonce   string      `json:"request_nonce"`
	Backend        string      `json:"backend"`
	ProofCalldata  [][]string  `json:"proof_calldata,omitempty"`
	Warnings       []string    `json:"warnings,omitempty"`
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
	cfg            config
	prover         proverEngine
	startedAt      time.Time
	lastHeartbeat  atomic.Value
	lastProofAt    atomic.Value
	circuitHash    string
	requestCounter atomic.Uint64
}

func newApp(cfg config, prover proverEngine) *app {
	a := &app{
		cfg:       cfg,
		prover:    prover,
		startedAt: time.Now(),
	}
	a.lastHeartbeat.Store(time.Now())
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
	mux.Handle("/metrics", expvar.Handler())
	mux.HandleFunc("/debug/pprof/", pprof.Index)
	mux.HandleFunc("/debug/pprof/cmdline", pprof.Cmdline)
	mux.HandleFunc("/debug/pprof/profile", pprof.Profile)
	mux.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
	mux.HandleFunc("/debug/pprof/trace", pprof.Trace)
	return mux
}

func main() {
	cfg := loadConfig()
	prover := initProver(cfg)
	server := newApp(cfg, prover)

	go server.heartbeatLoop()

	logLine("info", "proover.start", map[string]any{
		"listen_addr": cfg.ListenAddr,
		"backend":     prover.Backend(),
		"version":     cfg.Version,
		"circuit":     server.circuitHash,
	})

	if err := http.ListenAndServe(cfg.ListenAddr, server.routes()); err != nil {
		logLine("error", "proover.shutdown", map[string]any{"error": err.Error()})
		os.Exit(1)
	}
}

// initProver chooses and initializes the requested backend. Only Groth16 is supported.
func initProver(cfg config) proverEngine {
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
	case backendMock:
		log.Fatalf("mock backend is disabled; provide Groth16 artifacts instead")
	case backendGroth16, backendAuto:
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
		now := time.Now()
		a.lastHeartbeat.Store(now)
		logLine("info", "proover.heartbeat", map[string]any{
			"timestamp": now.Format(time.RFC3339),
			"backend":   a.prover.Backend(),
		})
	}
}

func (a *app) healthHandler(w http.ResponseWriter, r *http.Request) {
	lastHeartbeat, _ := a.lastHeartbeat.Load().(time.Time)
	lastProof, _ := a.lastProofAt.Load().(time.Time)
	payload := map[string]any{
		"status":          "ok",
		"backend":         a.prover.Backend(),
		"version":         a.cfg.Version,
		"circuit_hash":    a.circuitHash,
		"uptime_seconds":  int(time.Since(a.startedAt).Seconds()),
		"last_heartbeat":  lastHeartbeat.Format(time.RFC3339),
		"last_proof_at":   lastProof.Format(time.RFC3339),
		"max_concurrency": a.cfg.MaxConcurrency,
		"ready":           a.prover.Ready(),
	}
	writeJSON(w, http.StatusOK, payload)
}

func (a *app) heartbeatHandler(w http.ResponseWriter, r *http.Request) {
	payload := map[string]any{
		"status":       "ok",
		"heartbeat_at": time.Now().UTC().Format(time.RFC3339),
	}
	writeJSON(w, http.StatusOK, payload)
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
	start := time.Now()

	logLine("info", "proover.request.accepted", map[string]any{
		"event_id":     req.EventID,
		"condition_id": req.ConditionID,
		"request_id":   requestID,
		"backend":      a.prover.Backend(),
	})

	result, err := a.prover.Generate(ctx, req)
	if err != nil {
		recordProofFailure()
		logLine("error", "proover.request.failed", map[string]any{
			"event_id":     req.EventID,
			"condition_id": req.ConditionID,
			"error":        err.Error(),
			"request_id":   requestID,
		})
		return settlementProofResponse{}, err
	}
	now := time.Now().UTC()
	a.lastProofAt.Store(now)

	logFields := map[string]any{
		"event_id":     req.EventID,
		"condition_id": req.ConditionID,
		"request_id":   requestID,
		"backend":      a.prover.Backend(),
	}
	logLine("info", "proover.request.succeeded", logFields)
	recordProofSuccess(time.Since(start))

	return settlementProofResponse{
		Proof:         result.Proof,
		PublicSignals: result.PublicSignals,
		CircuitHash:   a.circuitHash,
		GeneratedAt:   now,
		ProverVersion: a.cfg.Version,
		RequestNonce:  req.Nonce,
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
	case strings.TrimSpace(req.EventID) == "":
		return errors.New("event_id required")
	case strings.TrimSpace(req.ConditionID) == "":
		return errors.New("condition_id required")
	case strings.TrimSpace(req.TotalPool) == "":
		return errors.New("total_pool required")
	case strings.TrimSpace(req.WinningPool) == "":
		return errors.New("winning_pool required")
	case strings.TrimSpace(req.Nonce) == "":
		return errors.New("nonce required")
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

func logLine(level, event string, fields map[string]any) {
	payloadFields := make(map[string]any)
	requestID := "-"
	if fields != nil {
		for key, value := range fields {
			if key == "request_id" {
				if v, ok := value.(string); ok && v != "" {
					requestID = v
				}
				continue
			}
			payloadFields[key] = value
		}
	}
	payload, _ := json.Marshal(payloadFields)
	_, file, line, ok := runtime.Caller(2)
	location := "-"
	if ok {
		location = fmt.Sprintf("%s:%d", filepath.Base(file), line)
	}
	log.Printf(
		"%s | %s | proover | %s | %s | %s | %s",
		time.Now().UTC().Format(time.RFC3339Nano),
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
		logLine("error", "proover.encode_failed", map[string]any{"error": err.Error()})
	}
}

func writeError(w http.ResponseWriter, status int, code string, message string, err error) {
	if err != nil {
		logLine("warn", "proover.response.error", map[string]any{
			"code":    code,
			"error":   err.Error(),
			"status":  status,
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
		logLine("warn", "proover.invalid_env", map[string]any{"key": key, "value": value, "fallback": fallback})
		return fallback
	}
	if n <= 0 {
		return fallback
	}
	return n
}
