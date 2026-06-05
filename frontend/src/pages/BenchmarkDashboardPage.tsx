import { useCallback, useEffect, useRef, useState } from "react";
import {
  createBenchmarkRun,
  getBenchmarkRun,
  listBenchmarkRuns,
  type BenchmarkRunDetail,
  type BenchmarkRunListItem,
} from "../api/benchmark";
import { useAuth, usePermissions } from "../contexts/AuthContext";
import { Button } from "../components/ui/Button";
import { Badge, statusVariant } from "../components/ui/Badge";
import { formatMetric } from "../api/benchmark";

const POLL_MS = 2500;
const TERMINAL = new Set(["completed", "failed"]);

export function BenchmarkDashboardPage() {
  const { token } = useAuth();
  const { canReadBenchmark, canRunBenchmark } = usePermissions();
  const [runs, setRuns] = useState<BenchmarkRunListItem[]>([]);
  const [activeRun, setActiveRun] = useState<BenchmarkRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);

  const loadRuns = useCallback(async () => {
    if (!token || !canReadBenchmark) return;
    try {
      const data = await listBenchmarkRuns(token, { limit: 20 });
      setRuns(data.runs);
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  }, [token, canReadBenchmark]);

  const refreshRun = useCallback(
    async (runId: string) => {
      if (!token) return null;
      const detail = await getBenchmarkRun(token, runId);
      setActiveRun(detail);
      return detail;
    },
    [token],
  );

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (!activeRun || TERMINAL.has(activeRun.status)) return;

    pollRef.current = window.setInterval(() => {
      void refreshRun(activeRun.id).then((detail) => {
        if (detail && TERMINAL.has(detail.status)) {
          void loadRuns();
        }
      });
    }, POLL_MS);

    return () => {
      if (pollRef.current != null) window.clearInterval(pollRef.current);
    };
  }, [activeRun?.id, activeRun?.status, refreshRun, loadRuns]);

  async function startRun() {
    if (!token || !canRunBenchmark) return;
    setLoading(true);
    setError("");
    try {
      const created = await createBenchmarkRun(token);
      await loadRuns();
      const detail = await refreshRun(created.id);
      if (detail) setActiveRun(detail);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function selectRun(runId: string) {
    setError("");
    try {
      await refreshRun(runId);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  if (!canReadBenchmark) {
    return (
      <div className="page">
        <h1>Benchmark</h1>
        <p>你没有查看评测结果的权限。</p>
      </div>
    );
  }

  const metrics = activeRun?.metrics;

  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <h3>Benchmark Dashboard</h3>
          <p>Coach Agent 评测集指标与运行状态</p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <Button variant="secondary" onClick={() => void loadRuns()}>
            刷新列表
          </Button>
          {canRunBenchmark ? (
            <Button variant="primary" disabled={loading} onClick={() => void startRun()}>
              {loading ? "启动中…" : "启动评测"}
            </Button>
          ) : null}
        </div>
      </div>

      {error ? <p className="panel__error">{error}</p> : null}

      {activeRun && metrics ? (
        <div className="metrics-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "0.75rem", marginBottom: "1.5rem" }}>
          <MetricCard label="Intent Accuracy" value={formatMetric(metrics.intent_accuracy)} />
          <MetricCard label="Plan Agent Recall" value={formatMetric(metrics.plan_agent_recall)} />
          <MetricCard label="Citation Rate" value={formatMetric(metrics.citation_rate)} />
          <MetricCard label="Tool Recall" value={formatMetric(metrics.tool_recall)} />
          <MetricCard label="Safety Compliance" value={formatMetric(metrics.safety_compliance)} />
          <MetricCard label="Latency P95" value={metrics.latency_p95_ms != null ? `${metrics.latency_p95_ms} ms` : "—"} />
          <MetricCard label="Recovery P95" value={metrics.recovery_latency_p95_ms != null ? `${metrics.recovery_latency_p95_ms} ms` : "—"} />
          <MetricCard label="Passed" value={`${metrics.passed_count ?? 0} / ${metrics.sample_count ?? 0}`} />
        </div>
      ) : activeRun && !TERMINAL.has(activeRun.status) ? (
        <p>评测运行中（{activeRun.status}）… 自动轮询更新</p>
      ) : null}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Dataset</th>
              <th>Status</th>
              <th>Intent Acc.</th>
              <th>Started</th>
              <th>Finished</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 ? (
              <tr>
                <td colSpan={6}>暂无评测运行记录</td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr key={run.id} className={activeRun?.id === run.id ? "data-table__row--active" : undefined}>
                  <td>{run.dataset_name}</td>
                  <td>
                    <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
                  </td>
                  <td>{formatMetric(run.metrics?.intent_accuracy)}</td>
                  <td className="data-table__time">{run.started_at ? new Date(run.started_at).toLocaleString() : "—"}</td>
                  <td className="data-table__time">{run.finished_at ? new Date(run.finished_at).toLocaleString() : "—"}</td>
                  <td>
                    <Button variant="ghost" onClick={() => void selectRun(run.id)}>
                      查看
                    </Button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {activeRun && activeRun.results.length > 0 ? (
        <div className="table-wrap" style={{ marginTop: "1.5rem" }}>
          <h4>样本结果（{activeRun.results.length}）</h4>
          <table className="data-table">
            <thead>
              <tr>
                <th>Sample</th>
                <th>Expected</th>
                <th>Predicted</th>
                <th>Passed</th>
              </tr>
            </thead>
            <tbody>
              {activeRun.results.map((row) => (
                <tr key={row.id}>
                  <td className="data-table__title">{row.sample_id}</td>
                  <td>{row.expected_intent}</td>
                  <td>{row.predicted_intent ?? "—"}</td>
                  <td>
                    <Badge variant={row.passed ? "success" : "danger"}>{row.passed ? "pass" : "fail"}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-card" style={{ padding: "0.75rem", border: "1px solid var(--border, #e5e7eb)", borderRadius: "8px" }}>
      <div style={{ fontSize: "0.75rem", opacity: 0.7 }}>{label}</div>
      <div style={{ fontSize: "1.25rem", fontWeight: 600 }}>{value}</div>
    </div>
  );
}
