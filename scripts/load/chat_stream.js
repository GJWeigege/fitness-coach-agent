import http from "k6/http";
import { check, sleep } from "k6";

/**
 * k6 load script for Coach Agent SSE chat stream.
 *
 * Usage:
 *   k6 run scripts/load/chat_stream.js \
 *     -e BASE_URL=http://localhost:8000 \
 *     -e TOKEN=<admin_or_coach_demo_jwt>
 *
 * Optional:
 *   -e MESSAGE="我想增肌，每周怎么练？"
 *   -e VUS=5 -e DURATION=30s
 */

export const options = {
  vus: Number(__ENV.VUS || 3),
  duration: __ENV.DURATION || "30s",
  thresholds: {
    http_req_failed: ["rate<0.05"],
    checks: { rate: ["rate>0.90"] },
  },
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TOKEN = __ENV.TOKEN || "";
const MESSAGE = __ENV.MESSAGE || "帮我制定恢复期的训练和饮食计划";

function authHeaders() {
  return {
    Authorization: `Bearer ${TOKEN}`,
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
}

export default function chatStreamLoad() {
  if (!TOKEN) {
    throw new Error("Set TOKEN env var (login via POST /auth/login first).");
  }

  const sessionRes = http.post(
    `${BASE_URL}/chat/sessions`,
    JSON.stringify({ title: `k6-${__VU}-${Date.now()}` }),
    { headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" } },
  );
  check(sessionRes, { "session created": (r) => r.status === 200 || r.status === 201 });

  const sessionId = sessionRes.json("id");
  const streamRes = http.post(
    `${BASE_URL}/chat/stream?use_rag=true`,
    JSON.stringify({ session_id: sessionId, message: MESSAGE }),
    { headers: authHeaders(), timeout: "120s" },
  );

  check(streamRes, {
    "stream status 200": (r) => r.status === 200,
    "stream body has done or replace": (r) =>
      typeof r.body === "string" &&
      (r.body.includes('"type":"done"') ||
        r.body.includes('"type":"replace"') ||
        r.body.includes('"type":"delta"')),
  });

  sleep(1);
}
