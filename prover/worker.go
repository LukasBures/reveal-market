package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const workerQueuePath = "proof_queue.jsonl"
const workerQueueDeadLetterPath = "proof_queue.deadletter.jsonl"
const workerPollInterval = 2 * time.Second
const workerMaxAttempts = 3

type workerJob struct {
	RequestID string                 `json:"request_id"`
	Payload   settlementProofRequest `json:"payload"`
	Attempts  int                    `json:"attempts,omitempty"`
}

type workerDeadLetter struct {
	RequestID string `json:"request_id,omitempty"`
	Error     string `json:"error"`
	Raw       string `json:"raw,omitempty"`
	Attempts  int    `json:"attempts,omitempty"`
	FailedAt  string `json:"failed_at"`
}

func runWorker(a *app) {
	deadLetterPath := deadLetterPathForQueue(workerQueuePath)
	logLine("info", "prover.worker.start", map[string]any{
		"queue_path":         workerQueuePath,
		"dead_letter_path":   deadLetterPath,
		"max_retry_attempts": workerMaxAttempts,
	})
	if recovered, err := recoverWorkerProcessingFiles(workerQueuePath); err != nil {
		logLine("error", "prover.worker.recover_failed", map[string]any{
			"queue_path": workerQueuePath,
			"error":      err.Error(),
		})
	} else if recovered > 0 {
		logLine("info", "prover.worker.recovered", map[string]any{
			"queue_path": workerQueuePath,
			"files":      recovered,
		})
	}
	for {
		processed, err := processWorkerQueueOnce(a, workerQueuePath)
		if err != nil {
			logLine("error", "prover.worker.poll_failed", map[string]any{
				"queue_path": workerQueuePath,
				"error":      err.Error(),
			})
		}
		if !processed {
			time.Sleep(workerPollInterval)
		}
	}
}

func processWorkerQueueOnce(a *app, queuePath string) (bool, error) {
	processingPath, err := claimWorkerQueueFile(queuePath)
	if err != nil {
		return false, err
	}
	if processingPath == "" {
		return false, nil
	}
	processedFile := false
	defer func() {
		if !processedFile {
			return
		}
		if removeErr := os.Remove(processingPath); removeErr != nil && !errors.Is(removeErr, os.ErrNotExist) {
			logLine("warn", "prover.worker.cleanup_failed", map[string]any{
				"path":  processingPath,
				"error": removeErr.Error(),
			})
		}
	}()

	file, err := os.Open(processingPath)
	if err != nil {
		return true, fmt.Errorf("failed to open processing queue %s: %w", processingPath, err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0, 64*1024), 10*1024*1024)
	retryJobs := make([]workerJob, 0)
	deadLetters := make([]workerDeadLetter, 0)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var job workerJob
		if err := json.Unmarshal([]byte(line), &job); err != nil {
			logLine("warn", "prover.worker.job_decode_failed", map[string]any{
				"line":  line,
				"error": err.Error(),
			})
			deadLetters = append(deadLetters, workerDeadLetter{
				Error:    fmt.Sprintf("job_decode_failed:%v", err),
				Raw:      line,
				FailedAt: time.Now().UTC().Format(time.RFC3339Nano),
			})
			continue
		}
		_, err := a.generateProofResponse(
			context.Background(),
			job.Payload,
			job.RequestID,
			-1,
			job.RequestID,
		)
		if err != nil {
			job.Attempts++
			if job.Attempts < workerMaxAttempts {
				retryJobs = append(retryJobs, job)
			} else {
				deadLetters = append(deadLetters, workerDeadLetter{
					RequestID: job.RequestID,
					Error:     fmt.Sprintf("job_failed:%v", err),
					Attempts:  job.Attempts,
					FailedAt:  time.Now().UTC().Format(time.RFC3339Nano),
				})
			}
			logLine("error", "prover.worker.job_failed", map[string]any{
				"request_id": job.RequestID,
				"error":      err.Error(),
				"attempts":   job.Attempts,
			})
			continue
		}
		logLine("info", "prover.worker.job_succeeded", map[string]any{
			"request_id": job.RequestID,
		})
	}
	if err := scanner.Err(); err != nil {
		return true, fmt.Errorf("failed to scan queue file %s: %w", processingPath, err)
	}
	if len(retryJobs) > 0 {
		if err := appendWorkerJobs(queuePath, retryJobs); err != nil {
			return true, err
		}
		logLine("info", "prover.worker.jobs_requeued", map[string]any{
			"queue_path": queuePath,
			"count":      len(retryJobs),
		})
	}
	if len(deadLetters) > 0 {
		dlqPath := deadLetterPathForQueue(queuePath)
		if err := appendWorkerDeadLetters(dlqPath, deadLetters); err != nil {
			return true, err
		}
		logLine("warn", "prover.worker.jobs_deadlettered", map[string]any{
			"path":  dlqPath,
			"count": len(deadLetters),
		})
	}
	processedFile = true
	return true, nil
}

func claimWorkerQueueFile(queuePath string) (string, error) {
	processingPath := fmt.Sprintf("%s.processing.%d", queuePath, time.Now().UTC().UnixNano())
	if err := os.Rename(queuePath, processingPath); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return "", nil
		}
		return "", fmt.Errorf("failed to claim queue file %s: %w", queuePath, err)
	}
	return processingPath, nil
}

func recoverWorkerProcessingFiles(queuePath string) (int, error) {
	pattern := fmt.Sprintf("%s.processing.*", queuePath)
	paths, err := filepath.Glob(pattern)
	if err != nil {
		return 0, fmt.Errorf("failed to glob processing files: %w", err)
	}
	if len(paths) == 0 {
		return 0, nil
	}
	sort.Strings(paths)
	recovered := 0
	for _, path := range paths {
		jobs, err := readWorkerJobsFromFile(path)
		if err != nil {
			return recovered, err
		}
		if len(jobs) > 0 {
			if err := appendWorkerJobs(queuePath, jobs); err != nil {
				return recovered, err
			}
		}
		if err := os.Remove(path); err != nil && !errors.Is(err, os.ErrNotExist) {
			return recovered, fmt.Errorf("failed to remove recovered processing file %s: %w", path, err)
		}
		recovered++
	}
	return recovered, nil
}

func readWorkerJobsFromFile(path string) ([]workerJob, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("failed to open processing file %s: %w", path, err)
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	scanner.Buffer(make([]byte, 0, 64*1024), 10*1024*1024)
	jobs := make([]workerJob, 0)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		var job workerJob
		if err := json.Unmarshal([]byte(line), &job); err != nil {
			return nil, fmt.Errorf("failed to decode recovered queue line: %w", err)
		}
		jobs = append(jobs, job)
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("failed to scan recovered queue file %s: %w", path, err)
	}
	return jobs, nil
}

func appendWorkerJobs(path string, jobs []workerJob) error {
	if len(jobs) == 0 {
		return nil
	}
	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return fmt.Errorf("failed to open queue file %s for append: %w", path, err)
	}
	defer file.Close()

	encoder := json.NewEncoder(file)
	for _, job := range jobs {
		if err := encoder.Encode(job); err != nil {
			return fmt.Errorf("failed to append queue job: %w", err)
		}
	}
	return nil
}

func appendWorkerDeadLetters(path string, entries []workerDeadLetter) error {
	if len(entries) == 0 {
		return nil
	}
	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return fmt.Errorf("failed to open dead-letter file %s for append: %w", path, err)
	}
	defer file.Close()

	encoder := json.NewEncoder(file)
	for _, entry := range entries {
		if err := encoder.Encode(entry); err != nil {
			return fmt.Errorf("failed to append dead-letter entry: %w", err)
		}
	}
	return nil
}

func deadLetterPathForQueue(queuePath string) string {
	dir := filepath.Dir(queuePath)
	return filepath.Join(dir, workerQueueDeadLetterPath)
}
