package shared

import (
	"os"
	"strconv"
)

func getenv(key, fallback string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return fallback
}

func intEnv(key string, fallback int) int {
	val := getenv(key, "")
	if val == "" {
		return fallback
	}
	if parsed, err := strconv.Atoi(val); err == nil {
		return parsed
	}
	return fallback
}

func floatEnv(key string, fallback float64) float64 {
	val := getenv(key, "")
	if val == "" {
		return fallback
	}
	if parsed, err := strconv.ParseFloat(val, 64); err == nil {
		return parsed
	}
	return fallback
}
