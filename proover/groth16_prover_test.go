package main

import (
	"encoding/json"
	"testing"
)

func TestComputeSolidityCalldata(t *testing.T) {
	proof := map[string]any{
		"pi_a": []any{"1", "2", "0"},
		"pi_b": []any{
			[]any{"3", "4", "0"},
			[]any{"5", "6", "0"},
		},
		"pi_c": []any{"7", "8", "0"},
	}
	raw, err := json.Marshal(proof)
	if err != nil {
		t.Fatalf("failed to marshal proof: %v", err)
	}
	signals := []string{"9", "10"}
	calldata, warnings := computeSolidityCalldata(raw, signals)
	if len(warnings) != 0 {
		t.Fatalf("expected no warnings, got %v", warnings)
	}
	if len(calldata) != 2 {
		t.Fatalf("expected 2 calldata arrays, got %d", len(calldata))
	}
	expectedProof := []string{"0x1", "0x2", "0x3", "0x4", "0x5", "0x6", "0x7", "0x8"}
	for i, want := range expectedProof {
		if calldata[0][i] != want {
			t.Fatalf("proof calldata[%d] mismatch: got %s want %s", i, calldata[0][i], want)
		}
	}
	expectedSignals := []string{"0x9", "0xa"}
	for i, want := range expectedSignals {
		if calldata[1][i] != want {
			t.Fatalf("public signal %d mismatch: got %s want %s", i, calldata[1][i], want)
		}
	}
}

func TestComputeSolidityCalldataWarnings(t *testing.T) {
	_, warnings := computeSolidityCalldata([]byte(`not-json`), []string{})
	if len(warnings) == 0 {
		t.Fatalf("expected warnings for invalid payload")
	}
}

func TestComputeSolidityCalldataSignalWarning(t *testing.T) {
	proof := map[string]any{
		"pi_a": []any{"1", "2"},
		"pi_b": []any{
			[]any{"3", "4"},
			[]any{"5", "6"},
		},
		"pi_c": []any{"7", "8"},
	}
	raw, _ := json.Marshal(proof)
	calldata, warnings := computeSolidityCalldata(raw, []string{"not-number"})
	if len(calldata) != 1 {
		t.Fatalf("expected only proof calldata when signals fail, got %d arrays", len(calldata))
	}
	if len(warnings) == 0 {
		t.Fatalf("expected warning about signal normalization")
	}
}

func TestParseFlexibleBigInt(t *testing.T) {
	cases := []struct {
		input string
		want  string
	}{
		{"42", "42"},
		{"0x2a", "42"},
		{"-5", "-5"},
		{"0X10", "16"},
	}
	for _, tc := range cases {
		t.Run(tc.input, func(t *testing.T) {
			num, err := parseFlexibleBigInt(tc.input)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if num.String() != tc.want {
				t.Fatalf("value mismatch: got %s want %s", num.String(), tc.want)
			}
		})
	}
}

func TestParseProofErrors(t *testing.T) {
	payload := map[string]any{
		"pi_a": []any{"1", "2"},
		// missing pi_b
		"pi_c": []any{"3", "4"},
	}
	if _, err := parseProof(payload); err == nil {
		t.Fatalf("expected error when pi_b missing")
	}
}

func TestParseFlexibleNumber(t *testing.T) {
	num, err := parseFlexibleNumber("12-34", "nonce")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if num.String() != "1234" {
		t.Fatalf("expected hyphens to be removed, got %s", num.String())
	}
}

func TestParseHexField(t *testing.T) {
	value, err := parseHexField("0x2a", "hash")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if value.String() != "42" {
		t.Fatalf("expected 42, got %s", value.String())
	}
	if _, err := parseHexField("zz", "hash"); err == nil {
		t.Fatalf("expected error for invalid hex")
	}
}
