import { useEffect, useState } from "react";
import { fetchAgentRunDetail, fetchAgentRuns } from "../api/observability";
import { useAuth } from "../contexts/AuthContext";
import { useApp } from "../contexts/AppContext";
import { Badge } from "../components/ui/Badge";
import type { AgentRunDetail, AgentRunListItem } from "../types";

function formatPayload(payload: Record<string, unknown> | null): string | null {
  if (!payload || Object.keys(payload).length === 0) return null;
  const cot = payload.cot ?? payload.cot_trace ?? payload.reasoning;
  if (typeof cot === "string" && cot.trim()) return cot;
  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

export function AgentRunsPage() {
  const { token } = useAuth();
  const { setError } = useApp();
  const [runs, setRuns] = useState<AgentRunListItem[]>([]);
  const [selected, setSelected] = useState<AgentRunDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!token) return;
    void (async () => {
      setLoading(true);
      try {
        const data = await fetchAgentRuns(token, { limit: 50 });
        setRuns(data.runs || []);
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    })();
  }, [token, setError]);

  async function openRun(runId: string) {
    if (!token) return;
    try {
      setSelected(await fetchAgentRunDetail(token, runId));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="agent-runs-page page">
      <h2>Agent 运行记录</h2>
      {loading ? <p>加载中…</p> : null}
      <div className="agent-runs-layout">
        <div className="table-wrap">
          <table className="data-table agent-runs-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>意图</th>
                <th>状态</th>
                <th>观测步数</th>
                <th>耗时</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr
                  key={run.id}
                  onClick={() => void openRun(run.id)}
                  className={selected?.id === run.id ? "agent-runs-table__row agent-runs-table__row--active" : "agent-runs-table__row"}
                >
                  <td>{new Date(run.created_at).toLocaleString()}</td>
                  <td>{run.intent || "-"}</td>
                  <td>
                    <Badge variant={run.status === "completed" ? "success" : run.status === "failed" ? "danger" : "info"}>
                      {run.status}
                    </Badge>
                  </td>
                  <td>{run.step_count}</td>
                  <td>{run.total_latency_ms ?? "-"} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {selected ? (
          <aside className="agent-runs-detail">
            <h3>运行详情</h3>
            <p>trace: {selected.trace_id}</p>
            <p>session: {selected.session_id}</p>
            <p>intent: {selected.intent || "-"}</p>
            <p>model: {selected.model_name || "-"}</p>
            {selected.error_message ? <p className="text-error">{selected.error_message}</p> : null}
            <ol className="agent-runs-timeline">
              {selected.timeline.map((step) => {
                const payloadText = formatPayload(step.payload);
                return (
                  <li key={step.id}>
                    <div className="agent-runs-timeline__head">
                      <strong>{step.phase}</strong>
                      {step.duration_ms != null ? <span>{step.duration_ms}ms</span> : null}
                    </div>
                    <p>{step.summary || "(无摘要)"}</p>
                    {payloadText ? (
                      <details className="agent-runs-timeline__payload">
                        <summary>payload / CoT</summary>
                        <pre>{payloadText}</pre>
                      </details>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </aside>
        ) : (
          <aside className="agent-runs-detail agent-runs-detail--empty">选择一条记录查看详情</aside>
        )}
      </div>
    </div>
  );
}
