package main

import (
	"context"
	"encoding/json"
	"os"
	"time"
)

const workerQueuePath = "proof_queue.jsonl"

type workerJob struct {
	RequestID string                 `json:"request_id"`
	Payload   settlementProofRequest `json:"payload"`
}

func runWorker(a *app) {
	logLine("info", "prover.worker.start", map[string]any{
		"queue_path": workerQueuePath,
	})
	for {
		file, err := os.Open(workerQueuePath)
		if err != nil {
			time.Sleep(2 * time.Second)
			continue
		}
		decoder := json.NewDecoder(file)
		for decoder.More() {
			var job workerJob
			if err := decoder.Decode(&job); err != nil {
				break
			}
			_, err := a.generateProofResponse(
				context.Background(),
				job.Payload,
				job.RequestID,
				-1,
				job.RequestID,
			)
			if err != nil {
				logLine("error", "prover.worker.job_failed", map[string]any{
					"request_id": job.RequestID,
					"error":      err.Error(),
				})
			} else {
				logLine("info", "prover.worker.job_succeeded", map[string]any{
					"request_id": job.RequestID,
				})
			}
		}
		file.Close()
		time.Sleep(2 * time.Second)
	}
}
