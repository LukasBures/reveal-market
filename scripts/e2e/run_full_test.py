#!/usr/bin/env python3
"""Full end-to-end integration test orchestrator. Runs all phases sequentially."""

from __future__ import annotations

import importlib
import subprocess
import sys
import time

from utils import (
    API_URL,
    HEDGER_URL,
    PROVER_URL,
    RELAYER_URL,
    header,
    log,
    setup_logging,
)

import httpx

PHASES = [
    ("Phase 1: Funding & Setup", "setup_funding"),
    ("Phase 2: Market Creation", "create_market"),
    ("Phase 3: Place Bets", "commit_bet"),
    ("Phase 4-7: Resolve & Settle", "resolve_and_settle"),
    ("Phase 8: Claim Payouts", "claim_payout"),
]


def check_service_health() -> dict[str, bool]:
    """Check all services are healthy."""
    services = {
        "API": f"{API_URL}/healthz",
        "Relayer": f"{RELAYER_URL}/healthz",
        "Prover": f"{PROVER_URL}/healthz",
        "Hedger": f"{HEDGER_URL}/healthz/deep",
    }
    results = {}
    for name, url in services.items():
        try:
            resp = httpx.get(url, timeout=10)
            results[name] = resp.status_code == 200
            status = "healthy" if results[name] else f"unhealthy ({resp.status_code})"
        except Exception as exc:
            results[name] = False
            status = f"unreachable ({exc})"
        log.info("  %-10s %s", name, status)
    return results


def check_docker_logs() -> dict[str, list[str]]:
    """Scan docker logs for ERROR entries."""
    containers = ["reveal-market-api", "reveal-market-worker", "reveal-market-relayer",
                   "reveal-market-hedger", "reveal-market-prover"]
    errors = {}
    for c in containers:
        try:
            result = subprocess.run(
                ["docker", "logs", c, "--tail", "50"],
                capture_output=True, text=True, timeout=10,
            )
            combined = result.stdout + result.stderr
            error_lines = [line for line in combined.split("\n")
                           if "ERROR" in line or "CRITICAL" in line or "FATAL" in line]
            if error_lines:
                errors[c] = error_lines[-5:]  # last 5 errors
        except Exception:
            pass
    return errors


def main() -> int:
    setup_logging()
    overall_start = time.time()

    header("E2E Integration Test: Full Happy Path")
    log.info("")

    # -----------------------------------------------------------------------
    # Pre-flight health check
    # -----------------------------------------------------------------------
    log.info("--- Pre-flight Health Check ---")
    health = check_service_health()
    healthy_count = sum(1 for v in health.values() if v)
    log.info("Healthy: %d/%d services", healthy_count, len(health))

    if healthy_count < len(health):
        log.warning("Some services are unhealthy — test may fail. Continuing anyway...")
    log.info("")

    # -----------------------------------------------------------------------
    # Run phases
    # -----------------------------------------------------------------------
    results: dict[str, dict] = {}

    for phase_name, module_name in PHASES:
        header(f"Running: {phase_name}")
        phase_start = time.time()

        try:
            mod = importlib.import_module(module_name)
            exit_code = mod.main()
            elapsed = time.time() - phase_start
            results[phase_name] = {
                "status": "PASS" if exit_code == 0 else "FAIL",
                "exit_code": exit_code,
                "elapsed": f"{elapsed:.1f}s",
            }
            if exit_code != 0:
                log.error("%s FAILED (exit_code=%d) after %s", phase_name, exit_code, results[phase_name]["elapsed"])
                break
            else:
                log.info("%s PASSED in %s", phase_name, results[phase_name]["elapsed"])
        except Exception as exc:
            elapsed = time.time() - phase_start
            results[phase_name] = {
                "status": "ERROR",
                "error": str(exc),
                "elapsed": f"{elapsed:.1f}s",
            }
            log.error("%s ERROR after %s: %s", phase_name, results[phase_name]["elapsed"], exc, exc_info=True)
            break

        log.info("")

    # -----------------------------------------------------------------------
    # Phase 9: Observability verification
    # -----------------------------------------------------------------------
    header("Phase 9: Observability & Health Verification")

    log.info("--- Post-test Health Check ---")
    post_health = check_service_health()
    post_healthy = sum(1 for v in post_health.values() if v)
    log.info("Healthy: %d/%d services", post_healthy, len(post_health))

    log.info("")
    log.info("--- Docker Log Errors ---")
    docker_errors = check_docker_logs()
    if docker_errors:
        for container, errors in docker_errors.items():
            log.warning("  %s: %d recent errors", container, len(errors))
            for err in errors:
                log.warning("    %s", err[:120])
    else:
        log.info("  No ERROR-level entries found in docker logs")

    # Check hedger state
    log.info("")
    log.info("--- Hedger State ---")
    try:
        resp = httpx.get(f"{HEDGER_URL}/healthz/deep", timeout=10)
        hedger_state = resp.json()
        log.info("  Hedger deep health: %s", hedger_state.get("status", "unknown"))
    except Exception as exc:
        log.warning("  Hedger unreachable: %s", exc)

    # Check worker heartbeat
    log.info("")
    log.info("--- Worker Heartbeat ---")
    try:
        resp = httpx.get(
            f"{API_URL}/healthz/heartbeats",
            headers={"X-Internal-Secret": "REDACTED"},
            timeout=10,
        )
        if resp.status_code == 200:
            log.info("  Worker heartbeat: %s", resp.json())
        else:
            log.warning("  Worker heartbeat endpoint returned %d", resp.status_code)
    except Exception as exc:
        log.warning("  Worker heartbeat unreachable: %s", exc)

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    total_elapsed = time.time() - overall_start
    header("TEST SUMMARY")

    all_passed = True
    for phase_name, result in results.items():
        status = result["status"]
        elapsed = result["elapsed"]
        icon = "PASS" if status == "PASS" else "FAIL"
        log.info("  [%s] %-35s %s", icon, phase_name, elapsed)
        if status != "PASS":
            all_passed = False
            if "error" in result:
                log.info("         Error: %s", result["error"])

    log.info("")
    log.info("Total time: %.1fs", total_elapsed)
    log.info("Services healthy: %d/%d (before) -> %d/%d (after)",
             healthy_count, len(health), post_healthy, len(post_health))

    if docker_errors:
        log.info("Docker errors: %d containers with errors", len(docker_errors))
    else:
        log.info("Docker errors: none")

    log.info("")
    if all_passed:
        log.info("OVERALL: ALL PHASES PASSED")
        return 0
    else:
        log.error("OVERALL: TEST FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
