import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.RELAYER_BASE_URL || "http://localhost:8000";

export const options = {
  vus: Number(__ENV.VUS || 50),
  duration: __ENV.DURATION || "1m",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
  },
};

export default function () {
  const res = http.get(`${BASE_URL}/healthz`, {
    timeout: `${__ENV.REQUEST_TIMEOUT_MS || 2000}ms`,
  });

  check(res, {
    "health ok": (r) => r.status === 200,
  });

  sleep(Number(__ENV.SLEEP_SECONDS || 0.05));
}
