



- search is not working



  - reveal-market-api: Healthy; no error logs in last 2h. Health endpoint check failed because nothing is bound on localhost:8000 on the host (port is only exposed inside Docker). Not a service error.
  - reveal-market-streamer: Healthy; no error logs. Health endpoint check failed for the same reason (not bound to host on 8100).
  - reveal-market-prover: Healthy and ready; artifacts OK; Groth16 backend OK; last heartbeat recent. Health endpoint check failed because prover is bound to 8085 (container), and 9100 is not published on host.
  - reveal-market-worker: Healthy; warnings from Polymarket Gamma API for specific ids (codex-e2e-25, codex-e2e-auto-28) returning HTTP 422. This looks like expected/invalid ids; worker continues successfully.
  - reveal-market-relayer: Healthy; one warning in last 2h: relayer.health.owner_fetch_failed due to TimeoutError (2s). Otherwise clean.
  - reveal-market-frontend: Healthy; no error logs.
  
  - reveal-market-redis: Healthy but memory high (1.407 GiB / 1.5 GiB = 93.8%). Watch this; a spike could trigger eviction or OOM.
  - reveal-market-postgres: Healthy; normal vacuum/analyze/checkpoints; no errors.



• Here’s the deeper dive, based on live checks just now (2026-01-15 20:33:59 UTC).

  Redis deep status

  - Memory is at max: used_memory_human = 1.27G, maxmemory_human = 1.27G
  - maxmemory-policy = volatile-lru
  - evicted_keys = 199,303 (non-zero; eviction is happening)
  - keyspace_hits = 5,746,881, keyspace_misses = 296,778,451 (very high miss rate)
  - db0: keys=472,957, expires=472,095, avg_ttl~16.6h
    Impact: Redis is at the cap and evicting. With volatile-lru, only keys with TTL are eligible for eviction. Miss rate suggests cache churn. This is the main risk I see right now.






  