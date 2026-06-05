import { API_BASE, apiFetch, buildHeaders } from "./client";

export type BenchmarkMetrics = {
  sample_count?: number;
  intent_accuracy?: number;
  plan_agent_recall?: number | null;
  citation_rate?: number | null;
  tool_recall?: number | null;
  safety_compliance?: number | null;
  latency_p95_ms?: number | null;
  recovery_latency_p95_ms?: number | null;
  passed_count?: number;
};

export type BenchmarkRunListItem = {
  id: string;
  dataset_name: string;
  status: "pending" | "running" | "completed" | "failed";
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

export async function createBenchmarkRun(
  token: string,
  datasetName = "coach_eval",
): Promise<BenchmarkRunCreateResponse> {
  return apiFetch(`${API_BASE}/benchmark/runs`, {
    method: "POST",
    headers: buildHeaders(token, { "Content-Type": "application/json" }),
    body: JSON.stringify({ dataset_name: datasetName }),
  });
}

export function formatMetric(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value <= 1) return `${(value * 100).toFixed(1)}%`;
  return String(value);
}
