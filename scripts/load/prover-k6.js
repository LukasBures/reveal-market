import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.PROVER_BASE_URL || "http://localhost:8085";
const STREAM = __ENV.PROVER_STREAM === "1";
const SHARED_SECRET = __ENV.PROVER_SHARED_SECRET || "";

export const options = {
  vus: Number(__ENV.VUS || 20),
  duration: __ENV.DURATION || "1m",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1500"],
  },
};

const payload = {
  marketId: "0x123",
  merkleRoot: "0x" + "1".repeat(64),
  winningOutcomeId: "0",
  poolTotals: ["1000", "900"],
  totalEscrow: "1900",
  totalLiability: "2000",
  rakeBps: "50",
  circuitHash: "0xbeef",
};

export default function () {
  const url = `${BASE_URL}/api/v1/proofs/settlement${STREAM ? "?stream=1" : ""}`;
  const headers = { "Content-Type": "application/json" };
  if (SHARED_SECRET) {
    headers["X-Prover-Secret"] = SHARED_SECRET;
  }
  const res = http.post(url, JSON.stringify(payload), {
    headers,
    timeout: `${__ENV.REQUEST_TIMEOUT_MS || 5000}ms`,
  });

  check(res, {
    "status is 200": (r) => r.status === 200,
  });

  sleep(Number(__ENV.SLEEP_SECONDS || 0.1));
}
