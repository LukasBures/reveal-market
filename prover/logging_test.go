package main

import (
	"bytes"
	"log"
	"os"
	"strings"
	"testing"
)

func TestResolveLogLevelDefaultsToInfo(t *testing.T) {
	t.Setenv("PROVER_LOG_LEVEL", "")
	name, value := resolveLogLevel()
	if name != "INFO" || value != levelValue("INFO") {
		t.Fatalf("expected INFO (20), got %s (%d)", name, value)
	}
}

func TestResolveLogLevelRespectsEnv(t *testing.T) {
	t.Setenv("PROVER_LOG_LEVEL", "debug")
	name, value := resolveLogLevel()
	if name != "DEBUG" || value != levelValue("DEBUG") {
		t.Fatalf("expected DEBUG, got %s (%d)", name, value)
	}
}

func TestLogLineRespectsThreshold(t *testing.T) {
	prevName, prevValue := logLevelName, logLevelValue
	defer func() {
		logLevelName = prevName
		logLevelValue = prevValue
		log.SetOutput(os.Stdout)
	}()

	logLevelName = "INFO"
	logLevelValue = levelValue("INFO")

	var buf bytes.Buffer
	log.SetOutput(&buf)

	logLine("debug", "test.debug", nil)
	if buf.Len() != 0 {
		t.Fatalf("expected debug log to be skipped, got output: %s", buf.String())
	}

	logLine("info", "test.info", map[string]any{"foo": "bar"})
	out := buf.String()
	if !strings.Contains(out, "test.info") || !strings.Contains(out, `"foo":"bar"`) {
		t.Fatalf("expected info log to be emitted, got: %s", out)
	}
}

func TestLogLineAddsDefaults(t *testing.T) {
	prevName, prevValue := logLevelName, logLevelValue
	defer func() {
		logLevelName = prevName
		logLevelValue = prevValue
		log.SetOutput(os.Stdout)
	}()

	logLevelName = "INFO"
	logLevelValue = levelValue("INFO")

	var buf bytes.Buffer
	log.SetOutput(&buf)

	logLine("info", "prover.test", map[string]any{"foo": "bar"})
	out := buf.String()
	if !strings.Contains(out, `"service":"prover"`) {
		t.Fatalf("expected service to be injected, got: %s", out)
	}
	if !strings.Contains(out, `"event":"prover.test"`) {
		t.Fatalf("expected event to be injected, got: %s", out)
	}
	if !strings.Contains(out, " | - | ") {
		t.Fatalf("expected default request_id segment, got: %s", out)
	}
}
