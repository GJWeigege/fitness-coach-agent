import { API_BASE, apiFetch, buildHeaders } from "./client";
import type { AgentRunDetail, AgentRunListItem } from "../types";

export async function fetchAgentRuns(
  token: string,
  params?: { session_id?: string; status?: string; limit?: number }
): Promise<{ runs: AgentRunListItem[]; total: number }> {
  const url = new URL(`${API_BASE}/observability/runs`);
  if (params?.session_id) url.searchParams.set("session_id", params.session_id);
  if (params?.status) url.searchParams.set("status", params.status);
  if (params?.limit) url.searchParams.set("limit", String(params.limit));
  return apiFetch(url.toString(), { headers: buildHeaders(token) });
}

export async function fetchAgentRunDetail(token: string, runId: string): Promise<AgentRunDetail> {
  return apiFetch(`${API_BASE}/observability/runs/${runId}`, { headers: buildHeaders(token) });
}
