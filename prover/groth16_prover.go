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
	"log"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

var (
	bufferPool = sync.Pool{
		New: func() any {
			return new(bytes.Buffer)
		},
	}
	copyBufferPool = sync.Pool{
		New: func() any {
			b := make([]byte, 32*1024)
			return &b
		},
	}
)

// groth16Settings captures the external binaries/artifacts used during proof generation.
type groth16Settings struct {
	NodeBinary          string
	RapidSnarkBinary    string
	WitnessScriptPath   string
	WitnessBinary       string
	WasmPath            string
	ZKeyPath            string
	TempDir             string
	Timeout             time.Duration
	MaxConcurrency      int
	CircuitHashOverride string
	StrictValidation    bool
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
	if err := requireCommand(settings.RapidSnarkBinary); err != nil {
		return nil, err
	}
	if strings.TrimSpace(settings.WitnessBinary) == "" {
		if err := requireCommand(settings.NodeBinary); err != nil {
			return nil, err
		}
		if err := requireFile(settings.WitnessScriptPath); err != nil {
			return nil, err
		}
		if err := requireFile(settings.WasmPath); err != nil {
			return nil, err
		}
	} else if err := requireFile(settings.WitnessBinary); err != nil {
		return nil, err
	}
	if err := requireFile(settings.ZKeyPath); err != nil {
		return nil, err
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
	logLine("info", "prover.backend.ready", map[string]any{
		"backend":         prover.Backend(),
		"max_concurrency": settings.MaxConcurrency,
		"timeout_seconds": settings.Timeout.Seconds(),
		"witness_mode":    witnessMode(settings),
		"zkey_bytes":      fileSize(settings.ZKeyPath),
		"wasm_bytes":      fileSize(settings.WasmPath),
		"witness_bytes":   fileSize(settings.WitnessBinary),
	})
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

func (p *groth16Prover) IsBusy() bool {
	return len(p.sem) >= cap(p.sem)
}

func (p *groth16Prover) Generate(ctx context.Context, req settlementProofRequest) (*proofResult, error) {
	if p.settings.StrictValidation {
		if err := validateStrictRequest(req); err != nil {
			return nil, err
		}
	}
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
	if err := os.Chmod(workdir, 0o700); err != nil {
		return nil, newInternalError(fmt.Errorf("failed to secure temp dir: %w", err))
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
	if err := ctx.Err(); err != nil {
		return nil, newInternalError(err)
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
	start := time.Now()
	startFields := map[string]any{
		"stage":        "witness_generation",
		"witness_mode": witnessMode(p.settings),
		"input_bytes":  fileSize(inputFile),
	}
	if strings.TrimSpace(p.settings.WitnessBinary) == "" {
		startFields["wasm_bytes"] = fileSize(p.settings.WasmPath)
	}
	addMemorySnapshot(startFields)
	logLine("info", "prover.stage.start", startFields)
	if strings.TrimSpace(p.settings.WitnessBinary) != "" {
		args := []string{inputFile, witnessFile}
		if err := p.runCommand(ctx, p.settings.WitnessBinary, args, "witness_generation_cpp"); err != nil {
			failFields := map[string]any{
				"stage":         "witness_generation_cpp",
				"duration_ms":   time.Since(start).Milliseconds(),
				"input_bytes":   fileSize(inputFile),
				"witness_bytes": fileSize(witnessFile),
			}
			addMemorySnapshot(failFields)
			logLine("error", "prover.stage.failed", failFields)
			return err
		}
		completeFields := map[string]any{
			"stage":         "witness_generation_cpp",
			"duration_ms":   time.Since(start).Milliseconds(),
			"witness_bytes": fileSize(witnessFile),
		}
		addMemorySnapshot(completeFields)
		logLine("info", "prover.stage.completed", completeFields)
		return nil
	}
	args := []string{p.settings.WitnessScriptPath, p.settings.WasmPath, inputFile, witnessFile}
	if err := p.runCommand(ctx, p.settings.NodeBinary, args, "witness_generation"); err != nil {
		failFields := map[string]any{
			"stage":         "witness_generation",
			"duration_ms":   time.Since(start).Milliseconds(),
			"input_bytes":   fileSize(inputFile),
			"witness_bytes": fileSize(witnessFile),
		}
		addMemorySnapshot(failFields)
		logLine("error", "prover.stage.failed", failFields)
		return err
	}
	completeFields := map[string]any{
		"stage":         "witness_generation",
		"duration_ms":   time.Since(start).Milliseconds(),
		"witness_bytes": fileSize(witnessFile),
	}
	addMemorySnapshot(completeFields)
	logLine("info", "prover.stage.completed", completeFields)
	return nil
}

func (p *groth16Prover) runProve(ctx context.Context, witnessFile, proofFile, publicFile string) error {
	start := time.Now()
	startFields := map[string]any{
		"stage":         "groth16_prove",
		"witness_bytes": fileSize(witnessFile),
		"zkey_bytes":    fileSize(p.settings.ZKeyPath),
	}
	addMemorySnapshot(startFields)
	logLine("info", "prover.stage.start", startFields)
	args := []string{p.settings.ZKeyPath, witnessFile, proofFile, publicFile}
	if err := p.runCommand(ctx, p.settings.RapidSnarkBinary, args, "groth16_prove"); err != nil {
		failFields := map[string]any{
			"stage":         "groth16_prove",
			"duration_ms":   time.Since(start).Milliseconds(),
			"witness_bytes": fileSize(witnessFile),
			"proof_bytes":   fileSize(proofFile),
			"public_bytes":  fileSize(publicFile),
			"zkey_bytes":    fileSize(p.settings.ZKeyPath),
		}
		addMemorySnapshot(failFields)
		logLine("error", "prover.stage.failed", failFields)
		return err
	}
	completeFields := map[string]any{
		"stage":        "groth16_prove",
		"duration_ms":  time.Since(start).Milliseconds(),
		"proof_bytes":  fileSize(proofFile),
		"public_bytes": fileSize(publicFile),
	}
	addMemorySnapshot(completeFields)
	logLine("info", "prover.stage.completed", completeFields)
	return nil
}

func (p *groth16Prover) runCommand(ctx context.Context, binary string, args []string, stage string) error {
	start := time.Now()
	logLine("debug", "prover.command.started", map[string]any{
		"stage":  stage,
		"binary": binary,
		"args":   args,
	})
	stdout, stderr, err := runCommand(ctx, binary, args, "")
	duration := time.Since(start)
	if err != nil {
		msg := strings.TrimSpace(string(stderr))
		if msg == "" {
			msg = err.Error()
		}
		fields := map[string]any{
			"stage":       stage,
			"binary":      binary,
			"error":       msg,
			"args":        args,
			"duration_ms": duration.Milliseconds(),
		}
		if details := exitDetails(err); len(details) > 0 {
			for key, value := range details {
				fields[key] = value
			}
		}
		if ctx.Err() != nil {
			fields["context_error"] = ctx.Err().Error()
		}
		if len(stdout) > 0 {
			fields["stdout"] = truncateLogOutput(stdout)
		}
		if len(stderr) > 0 {
			fields["stderr"] = truncateLogOutput(stderr)
		}
		addMemorySnapshot(fields)
		logLine("error", "prover.command.failed", fields)
		return newInternalError(fmt.Errorf("%s failed: %s", stage, msg))
	}
	if len(stderr) > 0 {
		logLine("warn", "prover.command.stderr", map[string]any{
			"stage":       stage,
			"binary":      binary,
			"stderr":      truncateLogOutput(stderr),
			"duration_ms": duration.Milliseconds(),
		})
	}
	logLine("debug", "prover.command.completed", map[string]any{
		"stage":       stage,
		"binary":      binary,
		"duration_ms": duration.Milliseconds(),
		"stdout":      truncateLogOutput(stdout),
	})
	return nil
}

func runCommand(ctx context.Context, binary string, args []string, workdir string) ([]byte, []byte, error) {
	cmd := exec.CommandContext(ctx, binary, args...)
	if workdir != "" {
		cmd.Dir = workdir
	}
	setProcessGroup(cmd)
	stdout := bufferPool.Get().(*bytes.Buffer)
	stderr := bufferPool.Get().(*bytes.Buffer)
	stdout.Reset()
	stderr.Reset()
	defer func() {
		bufferPool.Put(stdout)
		bufferPool.Put(stderr)
	}()
	cmd.Stdout = stdout
	cmd.Stderr = stderr
	err := cmd.Run()
	if ctx.Err() != nil {
		terminateProcessGroup(cmd)
	}
	outCopy := append([]byte(nil), stdout.Bytes()...)
	errCopy := append([]byte(nil), stderr.Bytes()...)
	return outCopy, errCopy, err
}

func setProcessGroup(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

func terminateProcessGroup(cmd *exec.Cmd) {
	if cmd.Process == nil {
		return
	}
	if err := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL); err != nil {
		log.Printf("WARN | terminateProcessGroup: failed to kill process group %d: %v", cmd.Process.Pid, err)
	}
}

func witnessMode(settings groth16Settings) string {
	if strings.TrimSpace(settings.WitnessBinary) != "" {
		return "cpp"
	}
	return "node"
}

func fileSize(path string) int64 {
	if strings.TrimSpace(path) == "" {
		return 0
	}
	info, err := os.Stat(path)
	if err != nil || info.IsDir() {
		return 0
	}
	return info.Size()
}

func truncateLogOutput(data []byte) string {
	const maxLogBytes = 2048
	text := strings.TrimSpace(string(data))
	if len(text) <= maxLogBytes {
		return text
	}
	return text[:maxLogBytes] + "...(truncated)"
}

func exitDetails(err error) map[string]any {
	exitErr, ok := err.(*exec.ExitError)
	if !ok {
		return nil
	}
	fields := map[string]any{}
	if status, ok := exitErr.Sys().(syscall.WaitStatus); ok {
		fields["exit_code"] = status.ExitStatus()
		if status.Signaled() {
			fields["signal"] = status.Signal().String()
		}
	}
	return fields
}

func addMemorySnapshot(fields map[string]any) {
	var stats runtime.MemStats
	runtime.ReadMemStats(&stats)
	fields["go_mem_alloc_bytes"] = stats.Alloc
	fields["go_mem_sys_bytes"] = stats.Sys
	fields["go_mem_heap_inuse_bytes"] = stats.HeapInuse
	fields["go_mem_heap_idle_bytes"] = stats.HeapIdle
	fields["go_mem_heap_released_bytes"] = stats.HeapReleased
	fields["go_mem_num_gc"] = stats.NumGC
	if available, ok := readMemAvailableBytes(); ok {
		fields["mem_available_bytes"] = available
	}
	if limit, ok := readCgroupValue([]string{"/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"}); ok {
		fields["cgroup_memory_max_bytes"] = limit
	}
	if current, ok := readCgroupValue([]string{"/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes"}); ok {
		fields["cgroup_memory_current_bytes"] = current
	}
}

func readMemAvailableBytes() (uint64, bool) {
	data, err := os.ReadFile("/proc/meminfo")
	if err != nil {
		return 0, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		if !strings.HasPrefix(line, "MemAvailable:") {
			continue
		}
		parts := strings.Fields(line)
		if len(parts) < 2 {
			return 0, false
		}
		value, err := strconv.ParseUint(parts[1], 10, 64)
		if err != nil {
			return 0, false
		}
		return value * 1024, true
	}
	return 0, false
}

func readCgroupValue(paths []string) (uint64, bool) {
	for _, path := range paths {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		raw := strings.TrimSpace(string(data))
		if raw == "" || raw == "max" {
			continue
		}
		value, err := strconv.ParseUint(raw, 10, 64)
		if err != nil {
			continue
		}
		return value, true
	}
	return 0, false
}

func requireCommand(name string) error {
	cleaned := filepath.Clean(name)
	if cleaned != name && !strings.Contains(name, "/") {
		return fmt.Errorf("binary path contains suspicious components: %s", name)
	}
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
	buf := copyBufferPool.Get().(*[]byte)
	defer copyBufferPool.Put(buf)
	if _, err := io.CopyBuffer(hasher, file, *buf); err != nil {
		return "", err
	}
	return hex.EncodeToString(hasher.Sum(nil)), nil
}

func writeJSONFile(path string, payload any) error {
	buf := bufferPool.Get().(*bytes.Buffer)
	buf.Reset()
	defer bufferPool.Put(buf)
	encoder := json.NewEncoder(buf)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(payload); err != nil {
		return err
	}
	return os.WriteFile(path, buf.Bytes(), 0o600)
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
	signals := make([]string, len(raw))
	for i, item := range raw {
		signals[i] = item.String()
	}
	return signals, nil
}

func validateArtifacts(settings groth16Settings) error {
	artifacts := []string{settings.ZKeyPath}
	if strings.TrimSpace(settings.WitnessBinary) != "" {
		artifacts = append(artifacts, settings.WitnessBinary)
	} else {
		artifacts = append(artifacts, settings.WitnessScriptPath, settings.WasmPath)
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

	// Swap FQ2 components to match Solidity pairing precompile order.
	parts := []string{
		proof.PiA[0],
		proof.PiA[1],
		proof.PiB[0][1],
		proof.PiB[0][0],
		proof.PiB[1][1],
		proof.PiB[1][0],
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

func buildWitnessInput(req settlementProofRequest) (map[string]any, error) {
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
	if winningOutcome.Cmp(big.NewInt(2)) >= 0 {
		return nil, newValidationError("winning_outcome_id must be 0 or 1")
	}
	totalEscrow, err := parsePositiveDecimal(req.TotalEscrow, "total_escrow")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	totalLiability, err := parseNonNegativeDecimal(req.TotalLiability, "total_liability")
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
	if sumPools.Cmp(totalEscrow) > 0 {
		return nil, newValidationError("pool_totals cannot exceed total_escrow")
	}
	circuitHash, err := parseHexField(req.CircuitHash, "circuit_hash")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	if _, err := parseFlexibleNumber(req.BatchIndex, "batch_index"); err != nil {
		return nil, newValidationError(err.Error())
	}
	commitmentsCount, err := parseFlexibleNumber(req.CommitmentsCount, "commitments_count")
	if err != nil {
		return nil, newValidationError(err.Error())
	}
	if commitmentsCount.Cmp(big.NewInt(settlementBatchSize)) > 0 {
		return nil, newValidationError("commitments_count must be <= 256")
	}
	if len(req.Tickets) != settlementBatchSize {
		return nil, newValidationError("tickets must contain 256 entries")
	}

	ticketIDs := make([]string, settlementBatchSize)
	outcomeIDs := make([]string, settlementBatchSize)
	amounts := make([]string, settlementBatchSize)
	payouts := make([]string, settlementBatchSize)
	users := make([]string, settlementBatchSize)
	salts := make([]string, settlementBatchSize)
	for i, ticket := range req.Tickets {
		ticketID, err := parseFlexibleNumber(ticket.TicketID, fmt.Sprintf("tickets[%d].ticket_id", i))
		if err != nil {
			return nil, newValidationError(err.Error())
		}
		outcomeID, err := parseFlexibleNumber(ticket.OutcomeID, fmt.Sprintf("tickets[%d].outcome_id", i))
		if err != nil {
			return nil, newValidationError(err.Error())
		}
		amountValue, err := parseFlexibleNumber(ticket.Amount, fmt.Sprintf("tickets[%d].amount", i))
		if err != nil {
			return nil, newValidationError(err.Error())
		}
		payoutValue, err := parseFlexibleNumber(ticket.Payout, fmt.Sprintf("tickets[%d].payout", i))
		if err != nil {
			return nil, newValidationError(err.Error())
		}
		userValue, err := parseFlexibleNumber(ticket.User, fmt.Sprintf("tickets[%d].user", i))
		if err != nil {
			return nil, newValidationError(err.Error())
		}
		saltValue, err := parseFlexibleNumber(ticket.Salt, fmt.Sprintf("tickets[%d].salt", i))
		if err != nil {
			return nil, newValidationError(err.Error())
		}
		ticketIDs[i] = fieldElement(ticketID).String()
		outcomeIDs[i] = fieldElement(outcomeID).String()
		amounts[i] = fieldElement(amountValue).String()
		payouts[i] = fieldElement(payoutValue).String()
		users[i] = fieldElement(userValue).String()
		salts[i] = fieldElement(saltValue).String()
	}

	inputs := map[string]any{
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
		"commitmentsCount": fieldElement(commitmentsCount).String(),
		"ticketId":         ticketIDs,
		"outcomeId":        outcomeIDs,
		"amount":           amounts,
		"payout":           payouts,
		"user":             users,
		"salt":             salts,
	}
	return inputs, nil
}

func validateStrictRequest(req settlementProofRequest) error {
	totalEscrow, err := parsePositiveDecimal(req.TotalEscrow, "total_escrow")
	if err != nil {
		return newValidationError(err.Error())
	}
	totalLiability, err := parseNonNegativeDecimal(req.TotalLiability, "total_liability")
	if err != nil {
		return newValidationError(err.Error())
	}
	rakeBps, err := parseNonNegativeDecimal(req.RakeBps, "rake_bps")
	if err != nil {
		return newValidationError(err.Error())
	}
	if rakeBps.Cmp(big.NewInt(10_000)) > 0 {
		return newValidationError("rake_bps must be <= 10000")
	}
	if len(req.PoolTotals) != 2 {
		return newValidationError("pool_totals must contain two entries")
	}
	poolYes, err := parseNonNegativeDecimal(req.PoolTotals[0], "pool_totals[0]")
	if err != nil {
		return newValidationError(err.Error())
	}
	poolNo, err := parseNonNegativeDecimal(req.PoolTotals[1], "pool_totals[1]")
	if err != nil {
		return newValidationError(err.Error())
	}
	sumPools := new(big.Int).Add(poolYes, poolNo)
	if sumPools.Cmp(totalEscrow) > 0 {
		return newValidationError("pool_totals cannot exceed total_escrow")
	}
	if totalLiability.Cmp(totalEscrow) > 0 {
		return newValidationError("total_liability cannot exceed total_escrow")
	}
	expectedRake := new(big.Int).Set(totalEscrow)
	expectedRake.Mul(expectedRake, rakeBps)
	expectedRake.Div(expectedRake, big.NewInt(10_000))
	expectedLiability := new(big.Int).Sub(totalEscrow, expectedRake)
	if totalLiability.Cmp(expectedLiability) != 0 {
		return newValidationError("total_liability does not match total_escrow and rake_bps")
	}
	commitmentsCount, err := parseFlexibleNumber(req.CommitmentsCount, "commitments_count")
	if err != nil {
		return newValidationError(err.Error())
	}
	if commitmentsCount.Cmp(big.NewInt(settlementBatchSize)) > 0 {
		return newValidationError("commitments_count must be <= 256")
	}
	if len(req.Tickets) != settlementBatchSize {
		return newValidationError("tickets must contain 256 entries")
	}
	return nil
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
		log.Fatalf("FATAL | mustBigInt: invalid big integer constant: %q", raw)
	}
	return num
}

func defaultString(value string, fallback string) string {
	if strings.TrimSpace(value) == "" {
		return fallback
	}
	return value
}
