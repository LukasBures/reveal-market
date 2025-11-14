package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
)

type settlementProofRequest struct {
	EventID       string            `json:"event_id"`
	ConditionID   string            `json:"condition_id"`
	TotalPool     string            `json:"total_pool"`
	WinningPool   string            `json:"winning_pool"`
	OutcomeHash   string            `json:"outcome_hash"`
	MarketAddress string            `json:"market_address"`
	Nonce         string            `json:"nonce"`
	CircuitVersion int              `json:"circuit_version"`
	Metadata      map[string]string `json:"metadata"`
}

type settlementProofResponse struct {
	Proof          string    `json:"proof"`
	PublicSignals  []string  `json:"public_signals"`
	CircuitHash    string    `json:"circuit_hash"`
	GeneratedAt    time.Time `json:"generated_at"`
	ProverVersion  string    `json:"prover_version"`
	RequestNonce   string    `json:"request_nonce"`
}

var (
	startedAt        = time.Now()
	lastHeartbeat    atomic.Value
	proverVersion    = getenv("PROVER_VERSION", "dev")
	circuitHash      = getenv("PROVER_CIRCUIT_HASH", "0x0")
	heartbeatSeconds = intEnv("PROVER_HEARTBEAT_SECONDS", 30)
	listenAddr       = getenv("PROVER_LISTEN_ADDR", "0.0.0.0:8085")
)

func main() {
	lastHeartbeat.Store(time.Now())
	go heartbeatLoop()

	http.HandleFunc("/healthz", healthHandler)
	http.HandleFunc("/heartbeat", heartbeatHandler)
	http.HandleFunc("/api/v1/proofs/settlement", proofHandler)

	log.Printf("proover listening on %s (version=%s)", listenAddr, proverVersion)
	if err := http.ListenAndServe(listenAddr, nil); err != nil {
		log.Fatalf("proover failed: %v", err)
	}
}

func heartbeatLoop() {
	ticker := time.NewTicker(time.Duration(heartbeatSeconds) * time.Second)
	defer ticker.Stop()
	for range ticker.C {
		now := time.Now()
		lastHeartbeat.Store(now)
		log.Printf("proover heartbeat at %s", now.Format(time.RFC3339))
	}
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	payload := map[string]any{
		"status":        "ok",
		"uptime_seconds": int(time.Since(startedAt).Seconds()),
		"version":       proverVersion,
		"circuit_hash":  circuitHash,
		"last_heartbeat": lastHeartbeat.Load().(time.Time).Format(time.RFC3339),
	}
	writeJSON(w, http.StatusOK, payload)
}

func heartbeatHandler(w http.ResponseWriter, r *http.Request) {
	payload := map[string]any{
		"status":        "ok",
		"heartbeat_at":  lastHeartbeat.Load().(time.Time).Format(time.RFC3339),
	}
	writeJSON(w, http.StatusOK, payload)
}

func proofHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	defer r.Body.Close()

	var req settlementProofRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid json payload", http.StatusBadRequest)
		return
	}
	if err := validateRequest(req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	resp := generateProof(req)
	writeJSON(w, http.StatusOK, resp)
}

func validateRequest(req settlementProofRequest) error {
	if req.EventID == "" {
		return errors.New("event_id required")
	}
	if req.ConditionID == "" {
		return errors.New("condition_id required")
	}
	if req.TotalPool == "" || req.WinningPool == "" {
		return errors.New("total_pool and winning_pool required")
	}
	if req.Nonce == "" {
		return errors.New("nonce required")
	}
	return nil
}

func generateProof(req settlementProofRequest) settlementProofResponse {
	body := map[string]any{
		"event_id":       req.EventID,
		"condition_id":   req.ConditionID,
		"total_pool":     req.TotalPool,
		"winning_pool":   req.WinningPool,
		"outcome_hash":   req.OutcomeHash,
		"market_address": req.MarketAddress,
		"nonce":          req.Nonce,
		"circuit_version": req.CircuitVersion,
		"metadata":       req.Metadata,
	}
	raw, _ := json.Marshal(body)
	digest := sha256.Sum256(raw)
	proof := hex.EncodeToString(digest[:])
	signals := []string{
		req.TotalPool,
		req.WinningPool,
		normalizeHex(req.OutcomeHash),
		fmt.Sprintf("%d", req.CircuitVersion),
		req.Nonce,
		normalizeAddress(req.MarketAddress),
	}
	return settlementProofResponse{
		Proof:         proof,
		PublicSignals: signals,
		CircuitHash:   circuitHash,
		GeneratedAt:   time.Now().UTC(),
		ProverVersion: proverVersion,
		RequestNonce:  req.Nonce,
	}
}

func normalizeHex(value string) string {
	v := strings.TrimPrefix(strings.ToLower(value), "0x")
	return "0x" + v
}

func normalizeAddress(value string) string {
	if value == "" {
		return "0x0000000000000000000000000000000000000000"
	}
	return normalizeHex(value)
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		log.Printf("failed to encode response: %v", err)
	}
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
		log.Printf("invalid %s=%s, using default %d", key, value, fallback)
		return fallback
	}
	if n <= 0 {
		return fallback
	}
	return n
}
