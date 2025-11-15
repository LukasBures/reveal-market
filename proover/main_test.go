package main

import "testing"

func TestValidateRequest(t *testing.T) {
	valid := settlementProofRequest{
		EventID:        "evt",
		ConditionID:    "0xabc",
		TotalPool:      "10",
		WinningPool:    "5",
		OutcomeHash:    "0x01",
		MarketAddress:  "0xabc",
		Nonce:          "123",
		CircuitVersion: 1,
	}
	if err := validateRequest(valid); err != nil {
		t.Fatalf("expected valid request, got error: %v", err)
	}

	cases := []struct {
		name   string
		modify func(req *settlementProofRequest)
	}{
		{"missing_event", func(req *settlementProofRequest) { req.EventID = "" }},
		{"missing_condition", func(req *settlementProofRequest) { req.ConditionID = "   " }},
		{"missing_total_pool", func(req *settlementProofRequest) { req.TotalPool = "" }},
		{"missing_winning_pool", func(req *settlementProofRequest) { req.WinningPool = "" }},
		{"missing_nonce", func(req *settlementProofRequest) { req.Nonce = "" }},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req := valid
			tc.modify(&req)
			if err := validateRequest(req); err == nil {
				t.Fatalf("expected error for %s", tc.name)
			}
		})
	}
}

func TestBuildWitnessInput(t *testing.T) {
	req := settlementProofRequest{
		EventID:        "evt",
		ConditionID:    "0xabc",
		TotalPool:      "10",
		WinningPool:    "5",
		OutcomeHash:    "0x20",
		MarketAddress:  "0xabc",
		Nonce:          "0x2a",
		CircuitVersion: 1,
	}
	inputs, err := buildWitnessInput(req)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	expected := map[string]string{
		"totalPool":      "10",
		"winningPool":    "5",
		"outcomeHash":    "32",
		"circuitVersion": "1",
		"nonce":          "42",
		"marketAddress":  "2748",
	}
	for key, want := range expected {
		if got := inputs[key]; got != want {
			t.Fatalf("input %s mismatch: got %s want %s", key, got, want)
		}
	}
}

func TestBuildWitnessInputErrors(t *testing.T) {
	req := settlementProofRequest{
		EventID:        "evt",
		ConditionID:    "0xabc",
		TotalPool:      "5",
		WinningPool:    "10",
		OutcomeHash:    "0x1",
		MarketAddress:  "0x1",
		Nonce:          "1",
		CircuitVersion: 1,
	}
	if _, err := buildWitnessInput(req); err == nil {
		t.Fatalf("expected error when winning pool exceeds total pool")
	}
}
