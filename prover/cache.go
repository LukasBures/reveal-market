package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"sync"
	"time"
)

type proofCache struct {
	ttl        time.Duration
	maxEntries int
	mu         sync.Mutex
	entries    map[string]cacheEntry
}

type cacheEntry struct {
	response settlementProofResponse
	storedAt time.Time
}

func newProofCache(ttl time.Duration, maxEntries int) *proofCache {
	if ttl <= 0 {
		ttl = 0
	}
	if maxEntries <= 0 {
		maxEntries = 0
	}
	return &proofCache{
		ttl:        ttl,
		maxEntries: maxEntries,
		entries:    make(map[string]cacheEntry),
	}
}

func (c *proofCache) get(key string) (settlementProofResponse, bool) {
	if c == nil || c.ttl == 0 || c.maxEntries == 0 {
		return settlementProofResponse{}, false
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	entry, ok := c.entries[key]
	if !ok {
		return settlementProofResponse{}, false
	}
	if c.ttl > 0 && time.Since(entry.storedAt) > c.ttl {
		delete(c.entries, key)
		return settlementProofResponse{}, false
	}
	return entry.response, true
}

func (c *proofCache) set(key string, resp settlementProofResponse) {
	if c == nil || c.ttl == 0 || c.maxEntries == 0 {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if len(c.entries) >= c.maxEntries {
		for k := range c.entries {
			delete(c.entries, k)
			break
		}
	}
	c.entries[key] = cacheEntry{response: resp, storedAt: time.Now().UTC()}
}

func cacheKeyFor(req settlementProofRequest, circuitHash string) string {
	payload := map[string]any{
		"marketId":    req.MarketID,
		"merkleRoot":  req.MerkleRoot,
		"batchIndex":  req.BatchIndex,
		"circuitHash": circuitHash,
		"tickets":     req.Tickets,
		"poolTotals":  req.PoolTotals,
		"totalEscrow": req.TotalEscrow,
		"totalLiab":   req.TotalLiability,
		"rakeBps":     req.RakeBps,
		"commitments": req.CommitmentsCount,
		"winning":     req.WinningOutcome,
	}
	raw, _ := json.Marshal(payload)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}
