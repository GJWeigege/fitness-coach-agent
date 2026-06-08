import { API_BASE, apiFetch, buildHeaders } from "./client";

export const BENCHMARK_QUICK_SAMPLE_LIMIT = 10;

export type BenchmarkMetrics = {
  sample_count?: number;
  dataset_total?: number;
  planned_sample_count?: number;
  subset_limit?: number;
  subset_sample_ids?: string[];
  intent_accuracy?: number;
  plan_agent_recall?: number | null;
  citation_rate?: number | null;
  tool_recall?: number | null;
  safety_compliance?: number | null;
  faithfulness?: number | null;
  latency_p95_ms?: number | null;
  recovery_latency_p95_ms?: number | null;
  passed_count?: number;
};

export type BenchmarkRunListItem = {
  id: string;
  dataset_name: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  created_by_user_id: string;
  created_by_username?: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  metrics: BenchmarkMetrics | null;
  error_message: string | null;
};

export type BenchmarkResultItem = {
  id: string;
  sample_id: string;
  question: string;
  expected_intent: string;
  predicted_intent: string | null;
  passed: boolean;
  metrics: Record<string, unknown> | null;
  agent_run_id: string | null;
};

export type BenchmarkRunDetail = BenchmarkRunListItem & {
  results: BenchmarkResultItem[];
};

export type BenchmarkRunListResponse = {
  runs: BenchmarkRunListItem[];
  total: number;
};

export type BenchmarkRunCreateResponse = {
  id: string;
  dataset_name: string;
  status: string;
};

export async function listBenchmarkRuns(
  token: string,
  params?: { limit?: number; offset?: number },
): Promise<BenchmarkRunListResponse> {
  const query = new URLSearchParams();
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.offset != null) query.set("offset", String(params.offset));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return apiFetch(`${API_BASE}/benchmark/runs${suffix}`, {
    headers: buildHeaders(token),
  });
}

export async function getBenchmarkRun(token: string, runId: string): Promise<BenchmarkRunDetail> {
  return apiFetch(`${API_BASE}/benchmark/runs/${runId}`, {
    headers: buildHeaders(token),
  });
}

export type BenchmarkRunCreateOptions = {
  datasetName?: string;
  sampleLimit?: number;
  sampleIds?: string[];
};

export async function createBenchmarkRun(
  token: string,
  options: BenchmarkRunCreateOptions | string = {},
): Promise<BenchmarkRunCreateResponse> {
  const normalized =
    typeof options === "string" ? { datasetName: options } : options;
  const body: Record<string, unknown> = {
    dataset_name: normalized.datasetName ?? "coach_eval",
  };
  if (normalized.sampleLimit != null) {
    body.sample_limit = normalized.sampleLimit;
  }
  if (normalized.sampleIds != null) {
    body.sample_ids = normalized.sampleIds;
  }
  return apiFetch(`${API_BASE}/benchmark/runs`, {
    method: "POST",
    headers: buildHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify(body),
  });
}

export async function cancelBenchmarkRun(
  token: string,
  runId: string,
): Promise<{ id: string; status: string }> {
  return apiFetch(`${API_BASE}/benchmark/runs/${runId}/cancel`, {
    method: "POST",
    headers: buildHeaders(token),
  });
}

/**
 * Benchmark failure reason codes — keep in sync with backend/app/services/benchmark_runner.py
 * (FR_* constants).
 */
export type BenchmarkFailureReasonCode =
  | "intent_mismatch"
  | "missing_citation"
  | "missing_disclaimer"
  | "banned_diagnosis"
  | "missing_safety_review"
  | "unfaithful_answer"
  | "run_error"
  | `missing_tools:${string}`
  | `plan_agents_mismatch:expected=${string},actual=${string}`;

export type BenchmarkFailureReasonEntry = {
  code: string;
  label: string;
};

export function formatFailureReason(code: string): string {
  if (code === "intent_mismatch") return "意图不匹配";
  if (code === "missing_citation") return "缺少知识引用";
  if (code === "missing_disclaimer") return "缺少免责声明";
  if (code === "banned_diagnosis") return "含禁止的诊断表述";
  if (code === "missing_safety_review") return "未记录安全审查步骤";
  if (code === "unfaithful_answer") return "回答与参考要点不符";
  if (code === "run_error") return "运行异常";

  if (code.startsWith("missing_tools:")) {
    const tools = code.slice("missing_tools:".length).split(",").filter(Boolean);
    if (tools.length === 0) return "缺少必需工具";
    return `缺少工具：${tools.join("、")}`;
  }

  if (code.startsWith("plan_agents_mismatch:")) {
    const rest = code.slice("plan_agents_mismatch:".length);
    const actualMarker = ",actual=";
    const actualIdx = rest.indexOf(actualMarker);
    if (actualIdx >= 0 && rest.startsWith("expected=")) {
      const expected = rest.slice("expected=".length, actualIdx) || "—";
      const actual = rest.slice(actualIdx + actualMarker.length) || "—";
      return `计划 agent 不匹配（期望 ${expected}，实际 ${actual}）`;
    }
  }

  return code;
}

export function getFailureReasonEntries(
  metrics: Record<string, unknown> | null | undefined,
): BenchmarkFailureReasonEntry[] {
  const raw = metrics?.failure_reasons;
  if (!Array.isArray(raw) || raw.length === 0) return [];
  return raw.map(String).map((code) => ({ code, label: formatFailureReason(code) }));
}

/** @deprecated Prefer getFailureReasonEntries for stable React keys */
export function getFailureReasons(metrics: Record<string, unknown> | null | undefined): string[] {
  return getFailureReasonEntries(metrics).map((entry) => entry.label);
}

export function formatMetric(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value <= 1) return `${(value * 100).toFixed(1)}%`;
  return String(value);
}
