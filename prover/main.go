package main

import (
	"context"
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
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
	"sync"
	"sync/atomic"
	"time"

	"github.com/reveal-market/prover/internal/shared"
)

const (
	defaultLogLevel       = "INFO"
	artifactCheckInterval = time.Minute
	settlementBatchSize   = 256
)

var (
	logLevelName  string
	logLevelValue int
)

func init() {
	log.SetFlags(0)
	logLevelName, logLevelValue = resolveLogLevel()
}

type settlementProofRequest struct {
	MarketID         string   `json:"marketId"`
	MerkleRoot       string   `json:"merkleRoot"`
	WinningOutcome   string   `json:"winningOutcomeId"`
	PoolTotals       []string `json:"poolTotals"`
	TotalEscrow      string   `json:"totalEscrow"`
	TotalLiability   string   `json:"totalLiability"`
	RakeBps          string   `json:"rakeBps"`
	CircuitHash      string   `json:"circuitHash"`
	BatchIndex       string   `json:"batchIndex"`
	CommitmentsCount string   `json:"commitmentsCount"`
	Tickets          []ticket `json:"tickets"`
}

type ticket struct {
	TicketID  string `json:"ticketId"`
	OutcomeID string `json:"outcomeId"`
	Amount    string `json:"amount"`
	Payout    string `json:"payout"`
	User      string `json:"user"`
	Salt      string `json:"salt"`
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

type proofStreamResult struct {
	resp settlementProofResponse
	err  error
}

// app bundles configuration, prover backend, and simple state for /healthz.
type app struct {
	cfg             shared.Config
	prover          proverEngine
	startedAt       time.Time
	lastHeartbeat   atomic.Value
	lastProofAt     atomic.Value
	circuitHash     string
	requestCounter  atomic.Uint64
	artifactCheck   artifactCheck
	artifactCheckMu sync.Mutex
	healthCache     healthCache
	proofQueue      chan struct{}
	cache           *proofCache
}

type artifactCheck struct {
	ok         bool
	missing    []string
	mismatches []string
	err        string
	checkedAt  time.Time
}

type healthCache struct {
	payload   []byte
	status    int
	expiresAt time.Time
	mu        sync.Mutex
}

func newApp(cfg shared.Config, prover proverEngine) *app {
	a := &app{
		cfg:       cfg,
		prover:    prover,
		startedAt: time.Now().UTC(),
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
	if cfg.AsyncQueueEnabled && cfg.QueueMaxDepth > 0 {
		a.proofQueue = make(chan struct{}, cfg.QueueMaxDepth)
	}
	a.cache = newProofCache(cfg.CacheTTL, cfg.CacheMaxEntries)
	return a
}

func (a *app) seedArtifactCheck(report shared.ArtifactReport) {
	now := time.Now().UTC()
	ok := len(report.Missing) == 0 && len(report.HashMismatches) == 0
	a.artifactCheckMu.Lock()
	a.artifactCheck = artifactCheck{
		ok:         ok,
		missing:    append([]string(nil), report.Missing...),
		mismatches: append([]string(nil), report.HashMismatches...),
		err:        "",
		checkedAt:  now,
	}
	a.artifactCheckMu.Unlock()
}

func (a *app) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", a.healthHandler)
	mux.HandleFunc("/heartbeat", a.heartbeatHandler)
	mux.HandleFunc("/api/v1/proofs/settlement", a.proofHandler)
	mux.HandleFunc("/api/v1/proofs/preflight", a.preflightHandler)
	mux.HandleFunc("/api/v1/proofs/warmup", a.warmupHandler)
	mux.HandleFunc("/metrics", promMetricsHandler)
	if a.cfg.EnableDebug {
		mux.Handle("/metrics/expvar", a.requireSecretHandler(expvar.Handler()))
		mux.HandleFunc("/debug/pprof/", a.requireSecret(pprof.Index))
		mux.HandleFunc("/debug/pprof/cmdline", a.requireSecret(pprof.Cmdline))
		mux.HandleFunc("/debug/pprof/profile", a.requireSecret(pprof.Profile))
		mux.HandleFunc("/debug/pprof/symbol", a.requireSecret(pprof.Symbol))
		mux.HandleFunc("/debug/pprof/trace", a.requireSecret(pprof.Trace))
	}
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
	if strings.TrimSpace(cfg.SharedSecret) == "" {
		logLine("error", "prover.config.missing_secret", map[string]any{
			"env": "RM_PROVER_SHARED_SECRET",
		})
		os.Exit(1)
	}
	if cfg.WorkerMode == "worker" {
		logLine("info", "prover.worker.mode", map[string]any{
			"mode": cfg.WorkerMode,
		})
	}
	report := requireArtifactsOrExit(cfg)
	verifiedCircuitHash := report.Hashes.CircuitHash
	if cfg.ManualCircuitHash != "" {
		matches, err := equalHex(cfg.ManualCircuitHash, verifiedCircuitHash)
		if err != nil || !matches {
			fields := map[string]any{
				"expected": verifiedCircuitHash,
				"provided": cfg.ManualCircuitHash,
			}
			if err != nil {
				fields["error"] = err.Error()
			}
			logLine("error", "prover.circuit_hash.mismatch", fields)
			os.Exit(1)
		}
	}
	cfg.ManualCircuitHash = verifiedCircuitHash
	prover := initProver(cfg)
	server := newApp(cfg, prover)
	server.seedArtifactCheck(report)

	go server.heartbeatLoop()

	if cfg.WorkerMode == "worker" {
		runWorker(server)
		return
	}

	logLine("info", "prover.start", map[string]any{
		"listen_addr": cfg.ListenAddr,
		"backend":     prover.Backend(),
		"version":     cfg.Version,
		"circuit":     server.circuitHash,
	})

	srv := &http.Server{
		Addr:              cfg.ListenAddr,
		Handler:           server.routes(),
		ReadHeaderTimeout: cfg.ReadHeaderTimeout,
		ReadTimeout:       cfg.ReadTimeout,
		WriteTimeout:      cfg.WriteTimeout,
		IdleTimeout:       cfg.IdleTimeout,
		MaxHeaderBytes:    cfg.MaxHeaderBytes,
	}

	if err := srv.ListenAndServe(); err != nil {
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
		WitnessBinary:     cfg.WitnessBinaryPath,
		WasmPath:          cfg.WasmPath,
		ZKeyPath:          cfg.ZKeyPath,
		TempDir:           cfg.TempDir,
		Timeout:           cfg.ProofTimeout,
		MaxConcurrency:    cfg.MaxConcurrency,
	}
	settings.CircuitHashOverride = cfg.ManualCircuitHash
	settings.StrictValidation = cfg.StrictValidation

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
	if cached := a.healthCache.read(); cached != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(cached.status)
		if _, err := w.Write(cached.payload); err != nil {
			logLine("error", "prover.health.cache_write_failed", map[string]any{"error": err.Error()})
		}
		return
	}
	lastHeartbeat, _ := a.lastHeartbeat.Load().(time.Time)
	lastProof, _ := a.lastProofAt.Load().(time.Time)
	artifactsOk, missing, mismatches, errMsg := a.verifyArtifacts()
	if artifactsOk {
		artifactsStatus.Set(1)
	} else {
		artifactsStatus.Set(0)
	}
	ready := a.prover.Ready() && artifactsOk
	payload := map[string]any{
		"status":            "ok",
		"backend":           a.prover.Backend(),
		"version":           a.cfg.Version,
		"circuit_hash":      a.circuitHash,
		"uptime_seconds":    int(time.Since(a.startedAt).Seconds()),
		"last_heartbeat":    formatMillis(lastHeartbeat),
		"last_proof_at":     formatMillis(lastProof),
		"max_concurrency":   a.cfg.MaxConcurrency,
		"ready":             ready,
		"artifacts_ok":      artifactsOk,
		"missing_artifacts": missing,
		"hash_mismatches":   mismatches,
	}
	if errMsg != "" {
		payload["artifact_error"] = errMsg
	}
	status := http.StatusOK
	if !ready {
		payload["status"] = "degraded"
		status = http.StatusServiceUnavailable
	}
	serialized := writeJSONBytes(w, status, payload)
	a.healthCache.store(serialized, status, a.cfg.HealthCacheSeconds)
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

func equalHex(left, right string) (bool, error) {
	leftValue, err := parseHexField(left, "circuit_hash")
	if err != nil {
		return false, err
	}
	rightValue, err := parseHexField(right, "circuit_hash")
	if err != nil {
		return false, err
	}
	return leftValue.Cmp(rightValue) == 0, nil
}

func requireArtifactsOrExit(cfg shared.Config) shared.ArtifactReport {
	report, err := shared.VerifyArtifacts(shared.ArtifactPaths{
		WitnessScriptPath:   cfg.WitnessScriptPath,
		WitnessBinaryPath:   cfg.WitnessBinaryPath,
		WasmPath:            cfg.WasmPath,
		ZKeyPath:            cfg.ZKeyPath,
		VerificationKeyPath: cfg.VerificationKeyPath,
		HashesPath:          cfg.HashesPath,
	})
	if err != nil {
		logLine("error", "prover.artifacts.invalid", map[string]any{"error": err.Error()})
		artifactsStatus.Set(0)
		os.Exit(1)
	}
	if len(report.Missing) > 0 {
		logLine("error", "prover.artifacts.missing", map[string]any{
			"missing": report.Missing,
		})
		artifactsStatus.Set(0)
		os.Exit(1)
	}
	if len(report.HashMismatches) > 0 {
		logLine("error", "prover.artifacts.hash_mismatch", map[string]any{
			"mismatches": report.HashMismatches,
		})
		artifactsStatus.Set(0)
		os.Exit(1)
	}
	if strings.TrimSpace(report.Hashes.CircuitHash) == "" {
		logLine("error", "prover.artifacts.invalid", map[string]any{
			"error": "circuit hash missing from settlement_hashes.json",
		})
		artifactsStatus.Set(0)
		os.Exit(1)
	}
	artifactsStatus.Set(1)
	logLine("info", "prover.artifacts.verified", map[string]any{
		"circuit_hash": report.Hashes.CircuitHash,
	})
	return report
}

func (a *app) verifyArtifacts() (bool, []string, []string, string) {
	now := time.Now().UTC()
	a.artifactCheckMu.Lock()
	defer a.artifactCheckMu.Unlock()

	if !a.artifactCheck.checkedAt.IsZero() && now.Sub(a.artifactCheck.checkedAt) < artifactCheckInterval {
		return a.artifactCheck.ok,
			append([]string(nil), a.artifactCheck.missing...),
			append([]string(nil), a.artifactCheck.mismatches...),
			a.artifactCheck.err
	}

	report, err := shared.VerifyArtifacts(shared.ArtifactPaths{
		WitnessScriptPath:   a.cfg.WitnessScriptPath,
		WitnessBinaryPath:   a.cfg.WitnessBinaryPath,
		WasmPath:            a.cfg.WasmPath,
		ZKeyPath:            a.cfg.ZKeyPath,
		VerificationKeyPath: a.cfg.VerificationKeyPath,
		HashesPath:          a.cfg.HashesPath,
	})
	errMsg := ""
	if err != nil {
		errMsg = err.Error()
	}
	missing := append([]string(nil), report.Missing...)
	mismatches := append([]string(nil), report.HashMismatches...)
	if err == nil {
		reportCircuit := strings.TrimSpace(report.Hashes.CircuitHash)
		runtimeCircuit := strings.TrimSpace(a.circuitHash)
		if reportCircuit == "" {
			mismatches = append(mismatches, "circuit hash missing from settlement_hashes.json")
		} else {
			match, cmpErr := equalHex(reportCircuit, runtimeCircuit)
			if cmpErr != nil {
				mismatches = append(mismatches, fmt.Sprintf("circuit_hash_compare_failed:%v", cmpErr))
			} else if !match {
				mismatches = append(
					mismatches,
					fmt.Sprintf("circuit_hash_drift expected=%s actual=%s", runtimeCircuit, reportCircuit),
				)
			}
		}
	}
	ok := err == nil && len(missing) == 0 && len(mismatches) == 0
	if !ok && errMsg == "" {
		errMsg = "artifact verification mismatch"
	}
	a.artifactCheck = artifactCheck{
		ok:         ok,
		missing:    missing,
		mismatches: mismatches,
		err:        errMsg,
		checkedAt:  now,
	}

	return ok, append([]string(nil), missing...), append([]string(nil), mismatches...), errMsg
}

func (a *app) readyForProof() (bool, []string, []string, string) {
	artifactsOk, missing, mismatches, errMsg := a.verifyArtifacts()
	if artifactsOk {
		artifactsStatus.Set(1)
	} else {
		artifactsStatus.Set(0)
	}
	if !artifactsOk || !a.prover.Ready() {
		return false, missing, mismatches, errMsg
	}
	return true, nil, nil, ""
}

func (a *app) requireSecret(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !a.authorizeSharedSecret(w, r) {
			return
		}
		next(w, r)
	}
}

func (a *app) requireSecretHandler(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !a.authorizeSharedSecret(w, r) {
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (a *app) authorizeSharedSecret(w http.ResponseWriter, r *http.Request) bool {
	secret := strings.TrimSpace(a.cfg.SharedSecret)
	if secret == "" {
		logLine("error", "prover.request.secret_missing", map[string]any{
			"path":   r.URL.Path,
			"method": r.Method,
		})
		writeError(w, http.StatusInternalServerError, "prover_secret_not_configured", "prover secret not configured", nil)
		return false
	}
	provided := strings.TrimSpace(r.Header.Get("X-Prover-Secret"))
	if subtle.ConstantTimeCompare([]byte(provided), []byte(secret)) != 1 {
		logLine("warn", "prover.request.unauthorized", map[string]any{
			"path":   r.URL.Path,
			"method": r.Method,
		})
		writeError(w, http.StatusUnauthorized, "unauthorized", "invalid prover secret", nil)
		return false
	}
	return true
}

func (a *app) proofHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		logLine("warn", "prover.request.invalid_method", map[string]any{
			"path":   r.URL.Path,
			"method": r.Method,
		})
		writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method not allowed", nil)
		return
	}
	if !a.authorizeSharedSecret(w, r) {
		return
	}
	ready, missing, mismatches, artifactErr := a.readyForProof()
	if !ready {
		logLine("warn", "prover.request.unready", map[string]any{
			"path":       r.URL.Path,
			"ready":      a.prover.Ready(),
			"missing":    missing,
			"mismatches": mismatches,
			"error":      artifactErr,
			"backend":    a.prover.Backend(),
			"circuit":    a.circuitHash,
			"request":    r.ContentLength,
			"streamed":   wantsStream(r),
		})
		writeError(w, http.StatusServiceUnavailable, "prover_unavailable", "prover not ready", nil)
		return
	}
	if a.prover.IsBusy() {
		writeError(w, http.StatusTooManyRequests, "busy", "prover at capacity", nil)
		return
	}
	defer r.Body.Close()

	if a.cfg.MaxRequestBytes > 0 {
		r.Body = http.MaxBytesReader(w, r.Body, a.cfg.MaxRequestBytes)
	}

	inputBytes := r.ContentLength

	var req settlementProofRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			logLine("warn", "prover.request.too_large", map[string]any{
				"path":   r.URL.Path,
				"limit":  a.cfg.MaxRequestBytes,
				"length": r.ContentLength,
			})
			writeError(w, http.StatusRequestEntityTooLarge, "payload_too_large", "request body too large", err)
			return
		}
		logLine("warn", "prover.request.decode_failed", map[string]any{
			"path":   r.URL.Path,
			"error":  err.Error(),
			"length": r.ContentLength,
		})
		writeError(w, http.StatusBadRequest, "invalid_json", "invalid json payload", err)
		return
	}
	if err := validateRequest(req); err != nil {
		logLine("warn", "prover.request.validation_failed", map[string]any{
			"path":   r.URL.Path,
			"error":  err.Error(),
			"market": req.MarketID,
		})
		writeError(w, http.StatusBadRequest, "invalid_request", err.Error(), err)
		return
	}
	if a.cfg.StrictValidation {
		if err := validateStrictRequest(req); err != nil {
			logLine("warn", "prover.request.strict_validation_failed", map[string]any{
				"path":   r.URL.Path,
				"error":  err.Error(),
				"market": req.MarketID,
			})
			writeError(w, http.StatusBadRequest, "invalid_request", err.Error(), err)
			return
		}
	}

	matches, err := equalHex(req.CircuitHash, a.circuitHash)
	if err != nil {
		logLine("warn", "prover.request.circuit_hash_invalid", map[string]any{
			"path":   r.URL.Path,
			"error":  err.Error(),
			"hash":   req.CircuitHash,
			"market": req.MarketID,
		})
		writeError(w, http.StatusBadRequest, "invalid_request", err.Error(), err)
		return
	}
	if !matches {
		logLine("warn", "prover.request.circuit_hash_mismatch", map[string]any{
			"path":     r.URL.Path,
			"provided": req.CircuitHash,
			"expected": a.circuitHash,
			"market":   req.MarketID,
		})
		writeError(w, http.StatusBadRequest, "invalid_request", "circuitHash does not match prover", nil)
		return
	}

	requestID := a.nextRequestID()
	traceID := strings.TrimSpace(r.Header.Get("X-Request-Id"))
	if traceID != "" {
		requestID = traceID
	}

	if wantsStream(r) {
		a.streamProof(w, r, req, requestID, inputBytes, traceID)
		return
	}

	resp, err := a.generateProofResponse(r.Context(), req, requestID, inputBytes, traceID)
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

func wantsStream(r *http.Request) bool {
	flag := strings.ToLower(strings.TrimSpace(r.URL.Query().Get("stream")))
	if flag == "1" || flag == "true" || flag == "yes" {
		return true
	}
	accept := strings.ToLower(r.Header.Get("Accept"))
	return strings.Contains(accept, "text/event-stream")
}

func (a *app) streamProof(w http.ResponseWriter, r *http.Request, req settlementProofRequest, requestID string, inputBytes int64, traceID string) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusBadRequest, "stream_unavailable", "streaming not supported", nil)
		return
	}
	ctx := r.Context()
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	w.WriteHeader(http.StatusOK)

	stream := func(event string, payload any) {
		writeSSE(w, event, payload)
		flusher.Flush()
	}

	stream("accepted", map[string]any{
		"request_id":   requestID,
		"status":       "accepted",
		"backend":      a.prover.Backend(),
		"circuit_hash": a.circuitHash,
	})

	resultCh := make(chan proofStreamResult, 1)
	go func() {
		resp, err := a.generateProofResponse(ctx, req, requestID, inputBytes, traceID)
		resultCh <- proofStreamResult{resp: resp, err: err}
		close(resultCh)
	}()

	for {
		select {
		case <-ctx.Done():
			stream("cancelled", map[string]any{
				"request_id": requestID,
				"status":     "cancelled",
				"message":    ctx.Err().Error(),
			})
			logLine("warn", "prover.request.cancelled", map[string]any{
				"request_id": requestID,
				"market_id":  req.MarketID,
				"reason":     ctx.Err().Error(),
			})
			return
		case res, ok := <-resultCh:
			if !ok {
				return
			}
			if res.err != nil {
				status := http.StatusInternalServerError
				code := "prover_error"
				message := "failed to generate proof"
				var perr *proverError
				if errors.As(res.err, &perr) {
					status = perr.status
					code = perr.code
					message = perr.err.Error()
				}
				stream("error", map[string]any{
					"request_id":  requestID,
					"status":      "failed",
					"http_status": status,
					"error":       code,
					"message":     message,
				})
				return
			}
			stream("proof", res.resp)
			return
		}
	}
}

func (a *app) generateProofResponse(ctx context.Context, req settlementProofRequest, requestID string, inputBytes int64, traceID string) (settlementProofResponse, error) {
	ctx, cancel := context.WithTimeout(ctx, a.cfg.RequestTimeout)
	defer cancel()
	cacheKey := cacheKeyFor(req, a.circuitHash)
	if cached, ok := a.cache.get(cacheKey); ok {
		cached.RequestID = requestID
		cached.GeneratedAt = formatMillis(time.Now().UTC())
		logLine("info", "prover.cache.hit", map[string]any{
			"market_id":   req.MarketID,
			"merkle_root": req.MerkleRoot,
			"request_id":  requestID,
			"trace_id":    traceID,
		})
		recordCacheHit()
		return cached, nil
	}
	if a.proofQueue != nil {
		select {
		case a.proofQueue <- struct{}{}:
			defer func() { <-a.proofQueue }()
		case <-time.After(a.cfg.QueueAcquireTimeout):
			return settlementProofResponse{}, &proverError{
				status: http.StatusTooManyRequests,
				code:   "queue_busy",
				err:    errors.New("proof queue busy"),
			}
		case <-ctx.Done():
			return settlementProofResponse{}, newInternalError(ctx.Err())
		}
	}
	start := time.Now().UTC()
	activeProofs.Add(1)
	defer activeProofs.Add(-1)

	logLine("info", "prover.request.accepted", map[string]any{
		"market_id":   req.MarketID,
		"merkle_root": req.MerkleRoot,
		"request_id":  requestID,
		"trace_id":    traceID,
		"backend":     a.prover.Backend(),
		"input_bytes": inputBytes,
	})
	if inputBytes > 0 {
		lastInputBytes.Set(float64(inputBytes))
	}
	ticketCount := float64(len(req.Tickets))
	lastTicketCount.Set(ticketCount)

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
	if err := validatePublicSignalsAgainstRequest(req, result.PublicSignals); err != nil {
		recordProofFailure()
		return settlementProofResponse{}, newInternalError(err)
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
		"input_bytes": inputBytes,
	}
	if len(result.Warnings) > 0 {
		logFields["warning_messages"] = result.Warnings
	}
	logLine("info", "prover.request.succeeded", logFields)
	recordProofSuccess(time.Since(start))

	resp := settlementProofResponse{
		Proof:         result.Proof,
		PublicSignals: result.PublicSignals,
		CircuitHash:   a.circuitHash,
		GeneratedAt:   formatMillis(now),
		ProverVersion: a.cfg.Version,
		RequestID:     requestID,
		Backend:       a.prover.Backend(),
		ProofCalldata: result.ProofCalldata,
		Warnings:      result.Warnings,
	}
	a.cache.set(cacheKey, resp)
	return resp, nil
}

func validatePublicSignalsAgainstRequest(req settlementProofRequest, signals []string) error {
	if len(signals) != 10 {
		return fmt.Errorf("unexpected public signal count: got %d, expected 10", len(signals))
	}
	inputs, err := buildWitnessInput(req)
	if err != nil {
		return fmt.Errorf("failed to derive expected public signals: %w", err)
	}
	expectedKeys := []string{
		"merkleRoot",
		"marketId",
		"winningOutcomeId",
		"totalEscrow",
		"totalLiability",
		"rakeBps",
		"poolTotalYes",
		"poolTotalNo",
		"circuitHash",
		"padding",
	}
	for idx, key := range expectedKeys {
		raw, ok := inputs[key]
		if !ok {
			return fmt.Errorf("missing derived signal %q", key)
		}
		expectedValue, ok := raw.(string)
		if !ok {
			return fmt.Errorf("derived signal %q has unexpected type", key)
		}
		expectedNum, err := parseFlexibleNumber(expectedValue, fmt.Sprintf("expected_%s", key))
		if err != nil {
			return fmt.Errorf("invalid derived signal %q: %w", key, err)
		}
		actualNum, err := parseFlexibleNumber(signals[idx], fmt.Sprintf("public_signal_%d", idx))
		if err != nil {
			return fmt.Errorf("invalid public signal %d: %w", idx, err)
		}
		if fieldElement(actualNum).Cmp(fieldElement(expectedNum)) != 0 {
			return fmt.Errorf(
				"public signal mismatch at index %d (%s): expected %s got %s",
				idx,
				key,
				fieldElement(expectedNum).String(),
				fieldElement(actualNum).String(),
			)
		}
	}
	return nil
}

func (a *app) nextRequestID() string {
	counter := a.requestCounter.Add(1)
	random := make([]byte, 6)
	if _, err := randRead(random); err != nil {
		return fmt.Sprintf("req-%d", counter)
	}
	return fmt.Sprintf("req-%d-%s", counter, hex.EncodeToString(random))
}

type proverEngine interface {
	Backend() string
	CircuitHash() string
	Ready() bool
	IsBusy() bool
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
	case strings.TrimSpace(req.BatchIndex) == "":
		return errors.New("batchIndex required")
	case strings.TrimSpace(req.CommitmentsCount) == "":
		return errors.New("commitmentsCount required")
	case len(req.Tickets) != settlementBatchSize:
		return fmt.Errorf("tickets must contain %d entries", settlementBatchSize)
	case containsDuplicateTicketIDs(req.Tickets):
		return errors.New("ticketId values must be unique")
	default:
		return nil
	}
}

func containsDuplicateTicketIDs(tickets []ticket) bool {
	seen := make(map[string]struct{}, len(tickets))
	for _, t := range tickets {
		id := strings.TrimSpace(t.TicketID)
		if id == "" {
			continue
		}
		if _, ok := seen[id]; ok {
			return true
		}
		seen[id] = struct{}{}
	}
	return false
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

func writeJSONBytes(w http.ResponseWriter, status int, payload any) []byte {
	data, err := json.Marshal(payload)
	if err != nil {
		logLine("error", "prover.encode_failed", map[string]any{"error": err.Error()})
		w.WriteHeader(status)
		return nil
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if _, err := w.Write(data); err != nil {
		logLine("error", "prover.encode_failed", map[string]any{"error": err.Error()})
	}
	return data
}

func (h *healthCache) read() *healthCache {
	if h == nil {
		return nil
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.payload == nil || h.expiresAt.IsZero() || time.Now().UTC().After(h.expiresAt) {
		return nil
	}
	return &healthCache{
		payload: append([]byte(nil), h.payload...),
		status:  h.status,
	}
}

func (h *healthCache) store(payload []byte, status int, ttlSeconds int) {
	if h == nil || ttlSeconds <= 0 || len(payload) == 0 {
		return
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	h.payload = append([]byte(nil), payload...)
	h.status = status
	h.expiresAt = time.Now().UTC().Add(time.Duration(ttlSeconds) * time.Second)
}

func randRead(buf []byte) (int, error) {
	if len(buf) == 0 {
		return 0, nil
	}
	return rand.Read(buf)
}

func writeSSE(w http.ResponseWriter, event string, payload any) {
	data, err := json.Marshal(payload)
	if err != nil {
		logLine("error", "prover.stream.encode_failed", map[string]any{"event": event, "error": err.Error()})
		return
	}
	fmt.Fprintf(w, "event: %s\n", event)
	fmt.Fprintf(w, "data: %s\n\n", data)
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

func (a *app) preflightHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method not allowed", nil)
		return
	}
	if !a.authorizeSharedSecret(w, r) {
		return
	}
	payload := map[string]any{
		"status":       "ok",
		"circuit_hash": a.circuitHash,
		"ready":        a.prover.Ready(),
	}
	writeJSON(w, http.StatusOK, payload)
}

func (a *app) warmupHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method not allowed", nil)
		return
	}
	if !a.authorizeSharedSecret(w, r) {
		return
	}
	ready, _, _, _ := a.readyForProof()
	if !ready {
		writeError(w, http.StatusServiceUnavailable, "prover_unavailable", "prover not ready", nil)
		return
	}
	if a.prover.IsBusy() {
		writeError(w, http.StatusTooManyRequests, "busy", "prover at capacity", nil)
		return
	}
	req, err := loadWarmupRequest(a.cfg)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "warmup_unavailable", err.Error(), err)
		return
	}
	resp, err := a.generateProofResponse(r.Context(), req, a.nextRequestID(), r.ContentLength, "")
	if err != nil {
		var perr *proverError
		if errors.As(err, &perr) {
			writeError(w, perr.status, perr.code, perr.err.Error(), perr.err)
			return
		}
		writeError(w, http.StatusInternalServerError, "prover_error", "failed to generate proof", err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status":     "ok",
		"request_id": resp.RequestID,
		"circuit":    resp.CircuitHash,
	})
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
