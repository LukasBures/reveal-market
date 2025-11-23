package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync/atomic"
	"time"
)

// groth16Settings captures the external binaries/artifacts used during proof generation.
type groth16Settings struct {
	NodeBinary          string
	RapidSnarkBinary    string
	WitnessScriptPath   string
	WasmPath            string
	ZKeyPath            string
	TempDir             string
	Timeout             time.Duration
	MaxConcurrency      int
	CircuitHashOverride string
}

// groth16Prover drives witness generation + rapidsnark proof creation.
type groth16Prover struct {
	settings    groth16Settings
	sem         chan struct{}
	circuitHash string
	ready       atomic.Bool
}

// newGroth16Prover validates binaries/artifacts and returns a ready-to-use backend.
func newGroth16Prover(settings groth16Settings) (*groth16Prover, error) {
	if settings.MaxConcurrency < 1 {
		settings.MaxConcurrency = 1
	}
	if settings.Timeout <= 0 {
		settings.Timeout = 2 * time.Minute
	}
	if err := requireCommand(settings.NodeBinary); err != nil {
		return nil, err
	}
	if err := requireCommand(settings.RapidSnarkBinary); err != nil {
		return nil, err
	}
	for _, path := range []string{settings.WitnessScriptPath, settings.WasmPath, settings.ZKeyPath} {
		if err := requireFile(path); err != nil {
			return nil, err
		}
	}
	if err := validateArtifacts(settings); err != nil {
		return nil, err
	}

	hash := strings.TrimSpace(settings.CircuitHashOverride)
	if hash == "" {
		digest, err := computeFileHash(settings.ZKeyPath)
		if err != nil {
			return nil, fmt.Errorf("failed to hash zkey: %w", err)
		}
		hash = "0x" + digest
	}

	prover := &groth16Prover{
		settings:    settings,
		sem:         make(chan struct{}, settings.MaxConcurrency),
		circuitHash: hash,
	}
	prover.ready.Store(true)
	return prover, nil
}

func (p *groth16Prover) Backend() string {
	return "groth16-rapidsnark"
}

func (p *groth16Prover) CircuitHash() string {
	return p.circuitHash
}

func (p *groth16Prover) Ready() bool {
	return p.ready.Load()
}

func (p *groth16Prover) Generate(ctx context.Context, req settlementProofRequest) (*proofResult, error) {
	inputs, err := buildWitnessInput(req)
	if err != nil {
		return nil, err
	}
	select {
	case p.sem <- struct{}{}:
		defer func() { <-p.sem }()
	case <-ctx.Done():
		return nil, newInternalError(ctx.Err())
	}

	jobCtx, cancel := context.WithTimeout(ctx, p.settings.Timeout)
	defer cancel()

	workdir, err := os.MkdirTemp(p.settings.TempDir, "groth16-")
	if err != nil {
		return nil, newInternalError(fmt.Errorf("failed to create temp dir: %w", err))
	}
	defer os.RemoveAll(workdir)

	inputFile := filepath.Join(workdir, "input.json")
	witnessFile := filepath.Join(workdir, "witness.wtns")
	proofFile := filepath.Join(workdir, "proof.json")
	publicFile := filepath.Join(workdir, "public.json")

	if err := writeJSONFile(inputFile, inputs); err != nil {
		return nil, newInternalError(fmt.Errorf("failed to write witness input: %w", err))
	}
	if err := p.runWitness(jobCtx, inputFile, witnessFile); err != nil {
		return nil, err
	}
	if err := p.runProve(jobCtx, witnessFile, proofFile, publicFile); err != nil {
		return nil, err
	}

	proofPayload, err := readFileAsString(proofFile)
	if err != nil {
		return nil, newInternalError(fmt.Errorf("failed to read proof output: %w", err))
	}
	publicSignals, err := readPublicSignals(publicFile)
	if err != nil {
		return nil, err
	}
	calldata, warnings := computeSolidityCalldata([]byte(proofPayload), publicSignals)

	return &proofResult{
		Proof:         proofPayload,
		PublicSignals: publicSignals,
		ProofCalldata: calldata,
		Warnings:      warnings,
	}, nil
}

func (p *groth16Prover) runWitness(ctx context.Context, inputFile, witnessFile string) error {
	args := []string{p.settings.WitnessScriptPath, p.settings.WasmPath, inputFile, witnessFile}
	if err := p.runCommand(ctx, p.settings.NodeBinary, args, "witness_generation"); err != nil {
		return err
	}
	return nil
}

func (p *groth16Prover) runProve(ctx context.Context, witnessFile, proofFile, publicFile string) error {
	args := []string{p.settings.ZKeyPath, witnessFile, proofFile, publicFile}
	if err := p.runCommand(ctx, p.settings.RapidSnarkBinary, args, "groth16_prove"); err != nil {
		return err
	}
	return nil
}

func (p *groth16Prover) runCommand(ctx context.Context, binary string, args []string, stage string) error {
	stdout, stderr, err := runCommand(ctx, binary, args, "")
	if err != nil {
		msg := strings.TrimSpace(string(stderr))
		if msg == "" {
			msg = err.Error()
		}
		logLine("error", "prover.command.failed", map[string]any{
			"stage":  stage,
			"binary": binary,
			"error":  msg,
			"args":   args,
		})
		return newInternalError(fmt.Errorf("%s failed: %s", stage, msg))
	}
	logLine("debug", "prover.command.completed", map[string]any{
		"stage":  stage,
		"binary": binary,
		"stdout": strings.TrimSpace(string(stdout)),
	})
	return nil
}

func runCommand(ctx context.Context, binary string, args []string, workdir string) ([]byte, []byte, error) {
	cmd := exec.CommandContext(ctx, binary, args...)
	if workdir != "" {
		cmd.Dir = workdir
	}
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	return stdout.Bytes(), stderr.Bytes(), err
}

func requireCommand(name string) error {
	if _, err := exec.LookPath(name); err != nil {
		return fmt.Errorf("command not found: %s", name)
	}
	return nil
}

func requireFile(path string) error {
	info, err := os.Stat(path)
	if err != nil {
		return fmt.Errorf("missing artifact: %s (%w)", path, err)
	}
	if info.IsDir() {
		return fmt.Errorf("expected file but found directory: %s", path)
	}
	return nil
}

func computeFileHash(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hasher := sha256.New()
	if _, err := io.Copy(hasher, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hasher.Sum(nil)), nil
}

func writeJSONFile(path string, payload any) error {
	data, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o600)
}

func readFileAsString(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(data)), nil
}

func readPublicSignals(path string) ([]string, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, newInternalError(fmt.Errorf("failed to read public signals: %w", err))
	}
	defer file.Close()
	decoder := json.NewDecoder(file)
	decoder.UseNumber()
	var raw []json.Number
	if err := decoder.Decode(&raw); err != nil {
		return nil, newInternalError(fmt.Errorf("invalid public signals payload: %w", err))
	}
	if len(raw) != 10 {
		return nil, newInternalError(fmt.Errorf("unexpected public signal count: got %d, expected 10", len(raw)))
	}
	signals := make([]string, 0, len(raw))
	for _, item := range raw {
		signals = append(signals, item.String())
	}
	return signals, nil
}

func validateArtifacts(settings groth16Settings) error {
	artifacts := []string{
		settings.WitnessScriptPath,
		settings.WasmPath,
		settings.ZKeyPath,
	}
	for _, path := range artifacts {
		info, err := os.Stat(path)
		if err != nil {
			return fmt.Errorf("artifact validation failed for %s: %w", path, err)
		}
		if info.Size() == 0 {
			return fmt.Errorf("artifact %s is empty", path)
		}
	}
	return nil
}

// computeSolidityCalldata converts rapidsnark's JSON outputs into the Solidity ABI-friendly layout.
func computeSolidityCalldata(proofJSON []byte, publicSignals []string) ([][]string, []string) {
	decoder := json.NewDecoder(bytes.NewReader(proofJSON))
	decoder.UseNumber()
	var payload map[string]any
	if err := decoder.Decode(&payload); err != nil {
		return nil, []string{fmt.Sprintf("failed to decode proof json: %v", err)}
	}

	proof, err := parseProof(payload)
	if err != nil {
		return nil, []string{fmt.Sprintf("invalid proof structure: %v", err)}
	}

	proofArgs, err := buildProofCalldata(proof)
	if err != nil {
		return nil, []string{fmt.Sprintf("failed to construct proof calldata: %v", err)}
	}

	publicArgs, err := normalizeSignals(publicSignals)
	if err != nil {
		return [][]string{proofArgs}, []string{fmt.Sprintf("failed to normalize public signals: %v", err)}
	}

	return [][]string{proofArgs, publicArgs}, nil
}

type rawProof struct {
	PiA []string
	PiB [][]string
	PiC []string
}

// parseProof pulls the pi_a/pi_b/pi_c coordinates from rapidsnark's proof.json payload.
func parseProof(payload map[string]any) (rawProof, error) {
	var proof rawProof
	var ok bool

	proof.PiA, ok = convertAnySlice(payload["pi_a"])
	if !ok {
		return proof, errors.New("pi_a missing or invalid")
	}
	piBRaw, ok := payload["pi_b"].([]any)
	if !ok || len(piBRaw) < 2 {
		return proof, errors.New("pi_b missing or invalid")
	}
	proof.PiB = make([][]string, len(piBRaw))
	for i, entry := range piBRaw {
		values, ok := convertAnySlice(entry)
		if !ok {
			return proof, fmt.Errorf("pi_b[%d] invalid", i)
		}
		proof.PiB[i] = values
	}
	proof.PiC, ok = convertAnySlice(payload["pi_c"])
	if !ok {
		return proof, errors.New("pi_c missing or invalid")
	}
	return proof, nil
}

// convertAnySlice coerces arbitrary JSON arrays (strings/floats) into string slices.
func convertAnySlice(value any) ([]string, bool) {
	items, ok := value.([]any)
	if !ok {
		return nil, false
	}
	result := make([]string, 0, len(items))
	for _, item := range items {
		switch v := item.(type) {
		case string:
			result = append(result, strings.TrimSpace(v))
		case json.Number:
			result = append(result, v.String())
		case float64:
			result = append(result, fmt.Sprintf("%.0f", v))
		default:
			return nil, false
		}
	}
	return result, true
}

// buildProofCalldata reorders proof coordinates to match the Solidity verifier ABI.
func buildProofCalldata(proof rawProof) ([]string, error) {
	if len(proof.PiA) < 2 || len(proof.PiB) < 2 || len(proof.PiB[0]) < 2 || len(proof.PiB[1]) < 2 || len(proof.PiC) < 2 {
		return nil, errors.New("proof points missing coordinates")
	}

	parts := []string{
		proof.PiA[0],
		proof.PiA[1],
		proof.PiB[0][0],
		proof.PiB[0][1],
		proof.PiB[1][0],
		proof.PiB[1][1],
		proof.PiC[0],
		proof.PiC[1],
	}
	result := make([]string, len(parts))
	for i, value := range parts {
		hexValue, err := toFieldHex(value)
		if err != nil {
			return nil, err
		}
		result[i] = hexValue
	}
	return result, nil
}

func normalizeSignals(signals []string) ([]string, error) {
	result := make([]string, len(signals))
	for i, value := range signals {
		hexValue, err := toFieldHex(value)
		if err != nil {
			return nil, err
		}
		result[i] = hexValue
	}
	return result, nil
}

func toFieldHex(value string) (string, error) {
	num, err := parseFlexibleBigInt(value)
	if err != nil {
		return "", err
	}
	field := fieldElement(num)
	if field.Sign() < 0 {
		field.Add(field, bn128Modulus)
	}
	return fmt.Sprintf("0x%s", field.Text(16)), nil
}

func parseFlexibleBigInt(value string) (*big.Int, error) {
	v := strings.TrimSpace(value)
	if v == "" {
		return nil, errors.New("empty field")
	}
	sign := 1
	if strings.HasPrefix(v, "-") {
		sign = -1
		v = strings.TrimPrefix(v, "-")
	}
	base := 10
	if strings.HasPrefix(v, "0x") || strings.HasPrefix(v, "0X") {
		base = 16
		v = v[2:]
	}
	num, ok := new(big.Int).SetString(v, base)
	if !ok {
		return nil, fmt.Errorf("invalid number: %s", value)
	}
	if sign < 0 {
		num.Neg(num)
	}
	return num, nil
}

var bn128Modulus = mustBigInt("21888242871839275222246405745257275088548364400416034343698204186575808495617")

func buildWitnessInput(req settlementProofRequest) (map[string]string, error) {
	merkleRoot, err := parseHexField(req.MerkleRoot, "merkle_root")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	marketID, err := parseFlexibleNumber(req.MarketID, "market_id")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	winningOutcome, err := parseFlexibleNumber(req.WinningOutcome, "winning_outcome_id")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	totalEscrow, err := parsePositiveDecimal(req.TotalEscrow, "total_escrow")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	totalLiability, err := parsePositiveDecimal(req.TotalLiability, "total_liability")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	rakeBps, err := parseNonNegativeDecimal(req.RakeBps, "rake_bps")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	if rakeBps.Cmp(big.NewInt(10_000)) > 0 {
		return nil, newValidationError("rake_bps must be <= 10000")
	}
	if len(req.PoolTotals) != 2 {
		return nil, newValidationError("pool_totals must contain two entries")
	}
	poolYes, err := parseNonNegativeDecimal(req.PoolTotals[0], "pool_totals[0]")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	poolNo, err := parseNonNegativeDecimal(req.PoolTotals[1], "pool_totals[1]")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	sumPools := new(big.Int).Add(poolYes, poolNo)
	if sumPools.Cmp(totalEscrow) != 0 {
		return nil, newValidationError("pool_totals must sum to total_escrow")
	}
	if len(req.Tickets) == 0 {
		return nil, newValidationError("tickets must be > 0")
	}
	circuitHash, err := parseHexField(req.CircuitHash, "circuit_hash")
	if err != nil {
		return nil, newValidationError(err.Error())
	}

	inputs := map[string]string{
		"merkleRoot":       fieldElement(merkleRoot).String(),
		"marketId":         fieldElement(marketID).String(),
		"winningOutcomeId": fieldElement(winningOutcome).String(),
		"totalEscrow":      fieldElement(totalEscrow).String(),
		"totalLiability":   fieldElement(totalLiability).String(),
		"rakeBps":          fieldElement(rakeBps).String(),
		"poolTotalYes":     fieldElement(poolYes).String(),
		"poolTotalNo":      fieldElement(poolNo).String(),
		"circuitHash":      fieldElement(circuitHash).String(),
		"padding":          "0",
	}
	return inputs, nil
}

func parsePositiveDecimal(value string, field string) (*big.Int, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return nil, fmt.Errorf("%s required", field)
	}
	num, ok := new(big.Int).SetString(trimmed, 10)
	if !ok {
		return nil, fmt.Errorf("%s must be decimal", field)
	}
	if num.Sign() <= 0 {
		return nil, fmt.Errorf("%s must be > 0", field)
	}
	return num, nil
}

func parseNonNegativeDecimal(value string, field string) (*big.Int, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return nil, fmt.Errorf("%s required", field)
	}
	num, ok := new(big.Int).SetString(trimmed, 10)
	if !ok {
		return nil, fmt.Errorf("%s must be decimal", field)
	}
	if num.Sign() < 0 {
		return nil, fmt.Errorf("%s must be >= 0", field)
	}
	return num, nil
}

func parseHexField(value string, field string) (*big.Int, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return nil, fmt.Errorf("%s required", field)
	}
	normalized := strings.TrimPrefix(strings.ToLower(trimmed), "0x")
	if normalized == "" {
		normalized = "0"
	}
	num, ok := new(big.Int).SetString(normalized, 16)
	if !ok {
		return nil, fmt.Errorf("%s must be hex", field)
	}
	return num, nil
}

func parseFlexibleNumber(value string, field string) (*big.Int, error) {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return nil, fmt.Errorf("%s required", field)
	}
	if strings.Contains(trimmed, "-") {
		return nil, fmt.Errorf("%s must be positive", field)
	}
	base := 10
	lower := strings.ToLower(trimmed)
	if strings.HasPrefix(lower, "0x") || strings.ContainsAny(lower, "abcdef") {
		base = 16
		lower = strings.TrimPrefix(lower, "0x")
		trimmed = lower
	}
	num, ok := new(big.Int).SetString(trimmed, base)
	if !ok {
		return nil, fmt.Errorf("%s must be numeric", field)
	}
	return num, nil
}

func fieldElement(value *big.Int) *big.Int {
	if value == nil {
		return big.NewInt(0)
	}
	result := new(big.Int).Mod(value, bn128Modulus)
	if result.Sign() < 0 {
		result.Add(result, bn128Modulus)
	}
	return result
}

func mustBigInt(raw string) *big.Int {
	num, ok := new(big.Int).SetString(raw, 10)
	if !ok {
		panic("invalid big integer constant")
	}
	return num
}

func defaultString(value string, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}
