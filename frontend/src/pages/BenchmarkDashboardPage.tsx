import { useCallback, useEffect, useRef, useState } from "react";
import {
  BENCHMARK_QUICK_SAMPLE_LIMIT,
  cancelBenchmarkRun,
  createBenchmarkRun,
  getBenchmarkRun,
  listBenchmarkRuns,
  type BenchmarkRunDetail,
  type BenchmarkRunListItem,
} from "../api/benchmark";
import { useAuth, usePermissions } from "../contexts/AuthContext";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { statusVariant } from "../components/ui/badgeVariants";
import { formatMetric } from "../api/benchmark";

const POLL_MS = 2500;
const PAGE_SIZE = 20;

const TERMINAL = new Set(["completed", "failed", "cancelled"]);
const ACTIVE = new Set(["pending", "running"]);

function findActiveRunId(runs: BenchmarkRunListItem[]): string | null {
  return runs.find((run) => ACTIVE.has(run.status))?.id ?? null;
}

function formatTools(metrics: Record<string, unknown> | null | undefined): string {
  const tools = metrics?.tool_names;
  if (!Array.isArray(tools) || tools.length === 0) return "—";
  return tools.map(String).join(", ");
}

export function BenchmarkDashboardPage() {
  const { token, me } = useAuth();
  const { canReadBenchmark, canRunBenchmark } = usePermissions();
  const [runs, setRuns] = useState<BenchmarkRunListItem[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [activeRun, setActiveRun] = useState<BenchmarkRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);
  const activeRunIdRef = useRef<string | null>(null);

  const loadRuns = useCallback(
    async (options?: { append?: boolean; offset?: number }) => {
      if (!token || !canReadBenchmark) return [] as BenchmarkRunListItem[];
      const offset = options?.offset ?? 0;
      try {
        const data = await listBenchmarkRuns(token, { limit: PAGE_SIZE, offset });
        setRunsTotal(data.total);
        setRuns((prev) => (options?.append ? [...prev, ...data.runs] : data.runs));
        setError("");
        return data.runs;
      } catch (err) {
        setError((err as Error).message);
        return [];
      }
    },
    [token, canReadBenchmark],
  );

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
    setRuns([]);
    setRunsTotal(0);
    setActiveRun(null);
    setError("");
  }, [token, me?.id]);

  useEffect(() => {
    void loadRuns().then((loaded) => {
      const runningId = findActiveRunId(loaded);
      if (runningId) {
        void refreshRun(runningId);
      }
    });
  }, [loadRuns, refreshRun]);

  const hasActiveRun =
    runs.some((run) => ACTIVE.has(run.status)) ||
    (activeRun != null && ACTIVE.has(activeRun.status));
  const cancellableRunId =
    (activeRun && ACTIVE.has(activeRun.status) ? activeRun.id : null) ?? findActiveRunId(runs);

  useEffect(() => {
    activeRunIdRef.current = cancellableRunId;
  }, [cancellableRunId]);

  useEffect(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (!hasActiveRun) return;

    pollRef.current = window.setInterval(() => {
      void loadRuns().then((loaded) => {
        const targetId = activeRunIdRef.current ?? findActiveRunId(loaded);
        if (targetId) {
          void refreshRun(targetId).then((detail) => {
            if (detail && TERMINAL.has(detail.status)) {
              void loadRuns();
            }
          });
        }
      });
    }, POLL_MS);

    return () => {
      if (pollRef.current != null) window.clearInterval(pollRef.current);
    };
  }, [hasActiveRun, loadRuns, refreshRun]);

  const metrics = activeRun?.metrics;
  const datasetTotal =
    activeRun?.metrics?.dataset_total ??
    runs.find((run) => run.metrics?.dataset_total != null)?.metrics?.dataset_total;

  async function startRun(sampleLimit?: number) {
    if (!token || !canRunBenchmark) return;
    if (hasActiveRun) {
      setError("已有评测正在运行，请等待结束或停止后再启动。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const created = await createBenchmarkRun(token, {
        sampleLimit,
      });
      await loadRuns();
      const detail = await refreshRun(created.id);
      if (detail) setActiveRun(detail);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function stopActiveRun() {
    if (!token || !canRunBenchmark || !cancellableRunId) return;
    setCancelling(true);
    setError("");
    try {
      await cancelBenchmarkRun(token, cancellableRunId);
      const detail = await refreshRun(cancellableRunId);
      if (detail) setActiveRun(detail);
      await loadRuns();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCancelling(false);
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

  async function loadMoreRuns() {
    if (!token || loadingMore || runs.length >= runsTotal) return;
    setLoadingMore(true);
    try {
      await loadRuns({ append: true, offset: runs.length });
    } finally {
      setLoadingMore(false);
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

  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <h3>Benchmark Dashboard</h3>
          <p>
            Coach Agent 评测集指标与运行状态。停止评测将在当前样本完成后生效。
            含参考答案的样本会评估 Faithfulness 并计入 Passed。
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <Button variant="secondary" onClick={() => void loadRuns()}>
            刷新列表
          </Button>
          {canRunBenchmark && cancellableRunId ? (
            <Button variant="danger" disabled={cancelling} onClick={() => void stopActiveRun()}>
              {cancelling ? "停止中…" : "停止评测"}
            </Button>
          ) : null}
          {canRunBenchmark ? (
            <>
              <Button
                variant="secondary"
                disabled={loading || hasActiveRun}
                onClick={() => void startRun(BENCHMARK_QUICK_SAMPLE_LIMIT)}
              >
                {loading ? "启动中…" : `快速评测 (${BENCHMARK_QUICK_SAMPLE_LIMIT} 条)`}
              </Button>
              <Button variant="primary" disabled={loading || hasActiveRun} onClick={() => void startRun()}>
                {loading ? "启动中…" : datasetTotal != null ? `完整评测 (${datasetTotal} 条)` : "完整评测"}
              </Button>
            </>
          ) : null}
        </div>
      </div>

      {error ? <p className="panel__error">{error}</p> : null}

      {activeRun?.status === "failed" && activeRun.error_message ? (
        <p className="panel__error" style={{ marginBottom: "1rem" }}>
          评测失败：{activeRun.error_message}
        </p>
      ) : null}

      {activeRun && metrics ? (
        <div className="metrics-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "0.75rem", marginBottom: "1.5rem" }}>
          <MetricCard label="Intent Accuracy" value={formatMetric(metrics.intent_accuracy)} />
          <MetricCard label="Plan Agent Recall" value={formatMetric(metrics.plan_agent_recall)} />
          <MetricCard label="Citation Rate" value={formatMetric(metrics.citation_rate)} />
          <MetricCard label="Tool Recall" value={formatMetric(metrics.tool_recall)} />
          <MetricCard label="Safety Compliance" value={formatMetric(metrics.safety_compliance)} />
          <MetricCard label="Faithfulness" value={formatMetric(metrics.faithfulness)} />
          <MetricCard label="Latency P95" value={metrics.latency_p95_ms != null ? `${metrics.latency_p95_ms} ms` : "—"} />
          <MetricCard label="Recovery P95" value={metrics.recovery_latency_p95_ms != null ? `${metrics.recovery_latency_p95_ms} ms` : "—"} />
          <MetricCard label="Passed" value={`${metrics.passed_count ?? 0} / ${metrics.sample_count ?? 0}`} />
        </div>
      ) : activeRun?.status === "cancelled" && activeRun.results.length === 0 ? (
        <p>评测已取消，无已完成样本。</p>
      ) : activeRun && !TERMINAL.has(activeRun.status) ? (
        <p>
          评测运行中（{activeRun.status}）… 已完成 {activeRun.results.length}
          {activeRun.metrics?.planned_sample_count != null
            ? ` / ${activeRun.metrics.planned_sample_count}`
            : ""}{" "}
          条，自动轮询更新
        </p>
      ) : hasActiveRun ? (
        <p>评测运行中… 自动轮询更新</p>
      ) : null}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Dataset</th>
              <th>Status</th>
              <th>Started By</th>
              <th>Intent Acc.</th>
              <th>Created</th>
              <th>Started</th>
              <th>Finished</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 ? (
              <tr>
                <td colSpan={8}>暂无评测运行记录</td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr key={run.id} className={activeRun?.id === run.id ? "data-table__row--active" : undefined}>
                  <td>{run.dataset_name}</td>
                  <td>
                    <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
                    {run.status === "failed" && run.error_message ? (
                      <div style={{ fontSize: "0.75rem", opacity: 0.8, marginTop: "0.25rem" }}>{run.error_message}</div>
                    ) : null}
                  </td>
                  <td>{run.created_by_username ?? "—"}</td>
                  <td>{formatMetric(run.metrics?.intent_accuracy)}</td>
                  <td className="data-table__time">
                    {run.created_at ? new Date(run.created_at).toLocaleString() : "—"}
                  </td>
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

      {runs.length < runsTotal ? (
        <div style={{ marginTop: "0.75rem" }}>
          <Button variant="secondary" disabled={loadingMore} onClick={() => void loadMoreRuns()}>
            {loadingMore ? "加载中…" : `加载更多 (${runs.length}/${runsTotal})`}
          </Button>
        </div>
      ) : null}

      {activeRun && activeRun.results.length > 0 ? (
        <div className="table-wrap" style={{ marginTop: "1.5rem" }}>
          <h4>样本结果（{activeRun.results.length}）</h4>
          <table className="data-table">
            <thead>
              <tr>
                <th>Sample</th>
                <th>Question</th>
                <th>Expected</th>
                <th>Predicted</th>
                <th>Latency</th>
                <th>Tools</th>
                <th>Passed</th>
              </tr>
            </thead>
            <tbody>
              {activeRun.results.map((row) => (
                <tr key={row.id}>
                  <td className="data-table__title">{row.sample_id}</td>
                  <td className="data-table__title" title={row.question}>
                    {row.question.length > 48 ? `${row.question.slice(0, 48)}…` : row.question}
                  </td>
                  <td>{row.expected_intent}</td>
                  <td>{row.predicted_intent ?? "—"}</td>
                  <td>
                    {typeof row.metrics?.latency_ms === "number" ? `${row.metrics.latency_ms} ms` : "—"}
                  </td>
                  <td>{formatTools(row.metrics)}</td>
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
