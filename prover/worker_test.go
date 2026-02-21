package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestProcessWorkerQueueOnceDrainsQueueFile(t *testing.T) {
	cfg := newTestConfig(t)
	payload := buildTestRequest()
	stub := &stubProver{
		ready:       true,
		circuitHash: "0x1",
		result: &proofResult{
			Proof:         `{"pi_a":["1","2"]}`,
			PublicSignals: expectedSignalsForRequest(t, payload),
		},
	}
	app := newApp(cfg, stub)

	job := workerJob{
		RequestID: "req-1",
		Payload:   payload,
	}
	line, err := json.Marshal(job)
	if err != nil {
		t.Fatalf("failed to marshal job: %v", err)
	}
	queuePath := filepath.Join(t.TempDir(), workerQueuePath)
	if err := os.WriteFile(queuePath, append(line, '\n'), 0o644); err != nil {
		t.Fatalf("failed to write queue file: %v", err)
	}

	processed, err := processWorkerQueueOnce(app, queuePath)
	if err != nil {
		t.Fatalf("unexpected process error: %v", err)
	}
	if !processed {
		t.Fatalf("expected queue file to be processed")
	}
	if stub.calls != 1 {
		t.Fatalf("expected one prover call, got %d", stub.calls)
	}

	processed, err = processWorkerQueueOnce(app, queuePath)
	if err != nil {
		t.Fatalf("unexpected second process error: %v", err)
	}
	if processed {
		t.Fatalf("expected no work after queue drain")
	}
	if stub.calls != 1 {
		t.Fatalf("expected no replay after queue drain")
	}
}

func TestProcessWorkerQueueOnceRequeuesFailedJob(t *testing.T) {
	cfg := newTestConfig(t)
	payload := buildTestRequest()
	stub := &stubProver{
		ready:       true,
		circuitHash: "0x1",
		err:         errors.New("prove failed"),
	}
	app := newApp(cfg, stub)

	job := workerJob{
		RequestID: "req-retry",
		Payload:   payload,
	}
	line, err := json.Marshal(job)
	if err != nil {
		t.Fatalf("failed to marshal job: %v", err)
	}
	queuePath := filepath.Join(t.TempDir(), workerQueuePath)
	if err := os.WriteFile(queuePath, append(line, '\n'), 0o644); err != nil {
		t.Fatalf("failed to write queue file: %v", err)
	}

	processed, err := processWorkerQueueOnce(app, queuePath)
	if err != nil {
		t.Fatalf("unexpected process error: %v", err)
	}
	if !processed {
		t.Fatalf("expected queue file to be processed")
	}
	raw, err := os.ReadFile(queuePath)
	if err != nil {
		t.Fatalf("failed to read requeued jobs: %v", err)
	}
	var requeued workerJob
	if err := json.Unmarshal(raw, &requeued); err != nil {
		t.Fatalf("failed to decode requeued job: %v", err)
	}
	if requeued.RequestID != "req-retry" {
		t.Fatalf("unexpected requeued request id: %s", requeued.RequestID)
	}
	if requeued.Attempts != 1 {
		t.Fatalf("expected attempts=1, got %d", requeued.Attempts)
	}
}

func TestRecoverWorkerProcessingFilesMovesOrphans(t *testing.T) {
	queueDir := t.TempDir()
	queuePath := filepath.Join(queueDir, workerQueuePath)
	payload := buildTestRequest()
	job := workerJob{RequestID: "req-orphan", Payload: payload}
	line, err := json.Marshal(job)
	if err != nil {
		t.Fatalf("failed to marshal job: %v", err)
	}
	processingPath := queuePath + ".processing.1"
	if err := os.WriteFile(processingPath, append(line, '\n'), 0o644); err != nil {
		t.Fatalf("failed to seed processing file: %v", err)
	}

	recovered, err := recoverWorkerProcessingFiles(queuePath)
	if err != nil {
		t.Fatalf("unexpected recover error: %v", err)
	}
	if recovered != 1 {
		t.Fatalf("expected one recovered processing file, got %d", recovered)
	}
	if _, err := os.Stat(processingPath); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("expected processing file to be removed, err=%v", err)
	}
	raw, err := os.ReadFile(queuePath)
	if err != nil {
		t.Fatalf("failed to read recovered queue: %v", err)
	}
	var restored workerJob
	if err := json.Unmarshal(raw, &restored); err != nil {
		t.Fatalf("failed to decode recovered job: %v", err)
	}
	if restored.RequestID != "req-orphan" {
		t.Fatalf("unexpected recovered request id: %s", restored.RequestID)
	}
}

func TestProcessWorkerQueueOnceDeadLettersMalformedJob(t *testing.T) {
	cfg := newTestConfig(t)
	app := newApp(cfg, &stubProver{ready: true, circuitHash: "0x1"})
	queueDir := t.TempDir()
	queuePath := filepath.Join(queueDir, workerQueuePath)
	if err := os.WriteFile(queuePath, []byte("{invalid-json}\n"), 0o644); err != nil {
		t.Fatalf("failed to write malformed queue file: %v", err)
	}

	processed, err := processWorkerQueueOnce(app, queuePath)
	if err != nil {
		t.Fatalf("unexpected process error: %v", err)
	}
	if !processed {
		t.Fatalf("expected malformed queue file to be processed")
	}
	dlqPath := deadLetterPathForQueue(queuePath)
	raw, err := os.ReadFile(dlqPath)
	if err != nil {
		t.Fatalf("failed to read dead-letter queue: %v", err)
	}
	var entry workerDeadLetter
	if err := json.Unmarshal(raw, &entry); err != nil {
		t.Fatalf("failed to decode dead-letter entry: %v", err)
	}
	if entry.Error == "" {
		t.Fatalf("expected dead-letter error to be populated")
	}
}
