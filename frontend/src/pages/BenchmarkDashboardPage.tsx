import { useCallback, useEffect, useRef, useState } from "react";
import {
  BENCHMARK_QUICK_SAMPLE_LIMIT,
  cancelBenchmarkRun,
  createBenchmarkRun,
  formatMetric,
  getBenchmarkRun,
  getFailureReasonEntries,
  listBenchmarkRuns,
  type BenchmarkRunDetail,
  type BenchmarkRunListItem,
  type BenchmarkResultItem,
} from "../api/benchmark";
import { useAuth, usePermissions } from "../contexts/AuthContext";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { statusVariant } from "../components/ui/badgeVariants";

const POLL_MS = 2500;
const PAGE_SIZE = 20;

const ACTIVE = new Set(["pending", "running"]);

const RUN_STATUS_LABELS: Record<string, string> = {
  pending: "等待中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const INTENT_LABELS: Record<string, string> = {
  training: "训练",
  nutrition: "营养",
  recovery: "恢复",
  safety: "安全",
  profile: "档案",
  chitchat: "闲聊",
  unknown: "未知",
};

const TOOL_LABELS: Record<string, string> = {
  knowledge_search: "知识检索",
  check_contraindication: "禁忌检查",
  get_user_profile: "用户档案",
  log_training: "训练记录",
  calculate_macros: "宏量计算",
  suggest_alternatives: "替代动作",
  graph_lookup: "图谱查询",
};

function findActiveRunId(runs: BenchmarkRunListItem[]): string | null {
  return runs.find((run) => ACTIVE.has(run.status))?.id ?? null;
}

function formatRunStatus(status: string): string {
  return RUN_STATUS_LABELS[status] ?? status;
}

function formatIntent(intent: string | null | undefined): string {
  if (!intent) return "—";
  return INTENT_LABELS[intent] ?? intent;
}

function formatToolName(name: string): string {
  return TOOL_LABELS[name] ?? name;
}

function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} 秒`;
  return `${ms} ms`;
}

function getTools(metrics: Record<string, unknown> | null | undefined): string[] {
  const tools = metrics?.tool_names;
  if (!Array.isArray(tools) || tools.length === 0) return [];
  return tools.map(String);
}

export function BenchmarkDashboardPage() {
  const { token, me } = useAuth();
  const { canReadBenchmark, canRunBenchmark } = usePermissions();
  const [runs, setRuns] = useState<BenchmarkRunListItem[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [listLoading, setListLoading] = useState(false);
  const [listRefreshing, setListRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<BenchmarkRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [loading, setLoading] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [optimisticActiveRunId, setOptimisticActiveRunId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const pollRef = useRef<number | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const selectedRunIdRef = useRef<string | null>(null);
  const runsLengthRef = useRef(0);
  const sessionRef = useRef(0);

  useEffect(() => {
    runsLengthRef.current = runs.length;
  }, [runs.length]);

  const applyRunDetail = useCallback((runId: string, detail: BenchmarkRunDetail | null) => {
    if (selectedRunIdRef.current !== runId) return;
    if (detail) setDetailError("");
    setSelectedRun(detail);
  }, []);

  const loadRuns = useCallback(
    async (options?: { append?: boolean; offset?: number; showLoading?: boolean }) => {
      if (!token || !canReadBenchmark) return [] as BenchmarkRunListItem[];
      const offset = options?.offset ?? 0;
      const showLoading = options?.showLoading ?? (!options?.append && offset === 0);
      const sessionAtStart = sessionRef.current;
      if (showLoading) setListLoading(true);
      try {
        const data = await listBenchmarkRuns(token, { limit: PAGE_SIZE, offset });
        if (sessionAtStart !== sessionRef.current) return [];
        setRunsTotal(data.total);
        setRuns((prev) => (options?.append ? [...prev, ...data.runs] : data.runs));
        setError("");
        return data.runs;
      } catch (err) {
        if (sessionAtStart === sessionRef.current) {
          setError((err as Error).message);
        }
        return [];
      } finally {
        if (showLoading && sessionAtStart === sessionRef.current) {
          setListLoading(false);
        }
      }
    },
    [token, canReadBenchmark],
  );

  const refreshRunsList = useCallback(async () => {
    if (!token || !canReadBenchmark) return [] as BenchmarkRunListItem[];
    const sessionAtStart = sessionRef.current;
    const limit = Math.max(PAGE_SIZE, runsLengthRef.current);
    try {
      const data = await listBenchmarkRuns(token, { limit, offset: 0 });
      if (sessionAtStart !== sessionRef.current) return [];
      setRunsTotal(data.total);
      setRuns(data.runs);
      setError("");
      return data.runs;
    } catch (err) {
      setError((err as Error).message);
      return [];
    }
  }, [token, canReadBenchmark]);

  const fetchRunDetail = useCallback(
    async (runId: string) => {
      if (!token) return null;
      return getBenchmarkRun(token, runId);
    },
    [token],
  );

  const loadRunDetail = useCallback(
    async (runId: string) => {
      setDetailLoading(true);
      setDetailError("");
      try {
        const detail = await fetchRunDetail(runId);
        if (selectedRunIdRef.current !== runId) return;
        if (detail) {
          applyRunDetail(runId, detail);
        }
      } catch (err) {
        if (selectedRunIdRef.current !== runId) return;
        setDetailError((err as Error).message);
        setSelectedRun(null);
      } finally {
        if (selectedRunIdRef.current === runId) {
          setDetailLoading(false);
        }
      }
    },
    [fetchRunDetail, applyRunDetail],
  );

  useEffect(() => {
    sessionRef.current += 1;
    setRuns([]);
    setRunsTotal(0);
    setSelectedRunId(null);
    setSelectedRun(null);
    setDetailError("");
    setOptimisticActiveRunId(null);
    setError("");
  }, [token, me?.id]);

  useEffect(() => {
    void loadRuns({ showLoading: true });
  }, [loadRuns]);

  useEffect(() => {
    if (!optimisticActiveRunId) return;
    if (runs.some((run) => run.id === optimisticActiveRunId)) {
      setOptimisticActiveRunId(null);
    }
  }, [runs, optimisticActiveRunId]);

  const hasActiveRun =
    runs.some((run) => ACTIVE.has(run.status)) || optimisticActiveRunId != null;
  const activeRunId = findActiveRunId(runs) ?? optimisticActiveRunId;
  const cancellableRunId = activeRunId;

  useEffect(() => {
    activeRunIdRef.current = cancellableRunId;
  }, [cancellableRunId]);

  useEffect(() => {
    selectedRunIdRef.current = selectedRunId;
  }, [selectedRunId]);

  useEffect(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (!hasActiveRun) return;

    pollRef.current = window.setInterval(() => {
      void refreshRunsList().then((loaded) => {
        const targetId = activeRunIdRef.current ?? findActiveRunId(loaded);
        if (!targetId || selectedRunIdRef.current !== targetId) return;
        void fetchRunDetail(targetId)
          .then((detail) => {
            if (!detail || selectedRunIdRef.current !== targetId) return;
            applyRunDetail(targetId, detail);
          })
          .catch((err: Error) => {
            if (selectedRunIdRef.current !== targetId) return;
            setDetailError(err.message);
          });
      });
    }, POLL_MS);

    return () => {
      if (pollRef.current != null) window.clearInterval(pollRef.current);
    };
  }, [hasActiveRun, refreshRunsList, fetchRunDetail, applyRunDetail]);

  const datasetTotal = runs.find((run) => run.metrics?.dataset_total != null)?.metrics?.dataset_total;

  async function handleRefreshList() {
    setListRefreshing(true);
    try {
      await refreshRunsList();
    } finally {
      setListRefreshing(false);
    }
  }

  async function startRun(sampleLimit?: number) {
    if (!token || !canRunBenchmark) return;
    if (hasActiveRun) {
      setError("已有评测正在运行，请等待结束或停止后再启动。");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const created = await createBenchmarkRun(token, { sampleLimit });
      setOptimisticActiveRunId(created.id);
      await loadRuns({ showLoading: false });
      setSelectedRunId(created.id);
      setSelectedRun(null);
      await loadRunDetail(created.id);
    } catch (err) {
      setOptimisticActiveRunId(null);
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
      await refreshRunsList();
      if (selectedRunIdRef.current === cancellableRunId) {
        await loadRunDetail(cancellableRunId);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCancelling(false);
    }
  }

  async function selectRun(runId: string) {
    if (selectedRunId === runId && selectedRun && !detailLoading) return;
    setSelectedRunId(runId);
    setSelectedRun(null);
    setError("");
    await loadRunDetail(runId);
  }

  function closeDetail() {
    setSelectedRunId(null);
    setSelectedRun(null);
    setDetailError("");
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
        <h1>评测看板</h1>
        <p>你没有查看评测结果的权限。</p>
      </div>
    );
  }

  return (
    <section className="panel">
      <div className="panel__header">
        <div>
          <h3>评测看板</h3>
          <p>
            Coach Agent 评测集指标与运行状态。停止评测将在当前样本完成后生效。
            含参考答案的样本会评估回答忠实度并计入通过数。
          </p>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <Button variant="secondary" disabled={listRefreshing} onClick={() => void handleRefreshList()}>
            {listRefreshing ? "刷新中…" : "刷新列表"}
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
                {loading ? "启动中…" : `快速评测（${BENCHMARK_QUICK_SAMPLE_LIMIT} 条）`}
              </Button>
              <Button variant="primary" disabled={loading || hasActiveRun} onClick={() => void startRun()}>
                {loading ? "启动中…" : datasetTotal != null ? `完整评测（${datasetTotal} 条）` : "完整评测"}
              </Button>
            </>
          ) : null}
        </div>
      </div>

      {error ? <p className="panel__error">{error}</p> : null}

      {hasActiveRun && !selectedRunId && activeRunId ? (
        <div className="benchmark-status benchmark-status--compact">
          <span className="benchmark-status__spinner" aria-hidden="true" />
          <span className="benchmark-status__text">有评测正在运行</span>
          <Button variant="secondary" onClick={() => void selectRun(activeRunId)}>
            查看进度
          </Button>
        </div>
      ) : null}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>数据集</th>
              <th>状态</th>
              <th>发起人</th>
              <th>意图准确率</th>
              <th>创建时间</th>
              <th>开始时间</th>
              <th>结束时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {listLoading ? (
              <tr>
                <td colSpan={8}>加载中…</td>
              </tr>
            ) : runs.length === 0 ? (
              <tr>
                <td colSpan={8}>暂无评测运行记录</td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr
                  key={run.id}
                  className={[
                    "data-table__row--clickable",
                    selectedRunId === run.id ? "data-table__row--active" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => void selectRun(run.id)}
                >
                  <td className="data-table__title">{run.dataset_name}</td>
                  <td>
                    <Badge variant={statusVariant(run.status)}>{formatRunStatus(run.status)}</Badge>
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
                    <Button
                      variant="ghost"
                      onClick={(e) => {
                        e.stopPropagation();
                        void selectRun(run.id);
                      }}
                    >
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
        <div className="benchmark-load-more">
          <Button variant="secondary" disabled={loadingMore} onClick={() => void loadMoreRuns()}>
            {loadingMore ? "加载中…" : `加载更多（${runs.length}/${runsTotal}）`}
          </Button>
        </div>
      ) : null}

      {selectedRunId ? (
        <BenchmarkRunDetailPanel
          run={selectedRun?.id === selectedRunId ? selectedRun : null}
          loading={detailLoading}
          error={detailError}
          onClose={closeDetail}
          onRetry={() => void loadRunDetail(selectedRunId)}
        />
      ) : null}
    </section>
  );
}

type BenchmarkRunDetailPanelProps = {
  run: BenchmarkRunDetail | null;
  loading: boolean;
  error: string;
  onClose: () => void;
  onRetry: () => void;
};

function BenchmarkRunDetailPanel({ run, loading, error, onClose, onRetry }: BenchmarkRunDetailPanelProps) {
  if (loading && !run) {
    return (
      <div className="benchmark-detail">
        <div className="benchmark-detail__loading">加载详情中…</div>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="benchmark-detail">
        <div className="benchmark-detail__header">
          <h4 className="benchmark-detail__title">运行详情</h4>
          <Button variant="ghost" onClick={onClose}>
            关闭
          </Button>
        </div>
        <div className="benchmark-detail__body">
          <p className="panel__error">{error || "无法加载运行详情。"}</p>
          <Button variant="secondary" onClick={onRetry}>
            重试
          </Button>
        </div>
      </div>
    );
  }

  const metrics = run.metrics;
  const plannedCount = metrics?.planned_sample_count;
  const completedCount = run.results.length;
  const progressPct =
    plannedCount && plannedCount > 0 ? Math.min(100, (completedCount / plannedCount) * 100) : null;
  const isActive = ACTIVE.has(run.status);

  return (
    <div className="benchmark-detail">
      <div className="benchmark-detail__header">
        <div>
          <h4 className="benchmark-detail__title">
            运行详情
            <Badge variant={statusVariant(run.status)}>{formatRunStatus(run.status)}</Badge>
          </h4>
          <div className="benchmark-detail__meta">
            <span>数据集：{run.dataset_name}</span>
            {run.created_by_username ? <span>发起人：{run.created_by_username}</span> : null}
            {run.started_at ? <span>开始：{new Date(run.started_at).toLocaleString()}</span> : null}
            {run.finished_at ? <span>结束：{new Date(run.finished_at).toLocaleString()}</span> : null}
          </div>
        </div>
        <Button variant="ghost" onClick={onClose}>
          关闭
        </Button>
      </div>

      <div className="benchmark-detail__body">
        {error ? (
          <p className="panel__error" style={{ marginBottom: "1rem" }}>
            详情刷新失败：{error}
          </p>
        ) : null}

        {run.status === "failed" && run.error_message ? (
          <p className="panel__error" style={{ marginBottom: "1rem" }}>
            评测失败：{run.error_message}
          </p>
        ) : null}

        {isActive ? (
          <div className="benchmark-status" style={{ marginBottom: "1.25rem" }}>
            <span className="benchmark-status__spinner" aria-hidden="true" />
            <div className="benchmark-status__text">
              评测进行中，已完成 {completedCount}
              {plannedCount != null ? ` / ${plannedCount}` : ""} 条，自动刷新中
              {progressPct != null ? (
                <div className="benchmark-status__progress">
                  <div className="benchmark-status__progress-bar" style={{ width: `${progressPct}%` }} />
                </div>
              ) : null}
            </div>
          </div>
        ) : null}

        {run.status === "cancelled" && run.results.length === 0 ? (
          <p className="benchmark-empty-hint">评测已取消，无已完成样本。</p>
        ) : null}

        {metrics ? (
          <div className="benchmark-metrics">
            <MetricCard label="意图准确率" value={formatMetric(metrics.intent_accuracy)} />
            <MetricCard label="计划召回率" value={formatMetric(metrics.plan_agent_recall)} />
            <MetricCard label="引用率" value={formatMetric(metrics.citation_rate)} />
            <MetricCard label="工具召回率" value={formatMetric(metrics.tool_recall)} />
            <MetricCard label="安全合规率" value={formatMetric(metrics.safety_compliance)} />
            <MetricCard label="回答忠实度" value={formatMetric(metrics.faithfulness)} />
            <MetricCard label="延迟 P95" value={formatLatency(metrics.latency_p95_ms)} />
            <MetricCard label="恢复延迟 P95" value={formatLatency(metrics.recovery_latency_p95_ms)} />
            <MetricCard
              label="通过数"
              value={`${metrics.passed_count ?? 0} / ${metrics.sample_count ?? 0}`}
              highlight
            />
          </div>
        ) : !isActive ? (
          <p className="benchmark-empty-hint">暂无指标数据。</p>
        ) : null}

        {run.results.length > 0 ? (
          <section className="benchmark-section">
            <h4 className="benchmark-section__title">
              样本结果
              <span className="benchmark-section__count">{run.results.length} 条</span>
            </h4>
            <div className="benchmark-result-list">
              {run.results.map((row) => (
                <BenchmarkResultCard key={row.id} row={row} />
              ))}
            </div>
          </section>
        ) : isActive ? (
          <p className="benchmark-empty-hint">等待首个样本完成…</p>
        ) : null}
      </div>
    </div>
  );
}

function BenchmarkResultCard({ row }: { row: BenchmarkResultItem }) {
  const tools = getTools(row.metrics);
  const failureReasons = !row.passed ? getFailureReasonEntries(row.metrics) : [];
  const intentMismatch = row.predicted_intent != null && row.predicted_intent !== row.expected_intent;
  const latencyMs = typeof row.metrics?.latency_ms === "number" ? row.metrics.latency_ms : null;

  return (
    <article
      className={`benchmark-result-card ${row.passed ? "benchmark-result-card--passed" : "benchmark-result-card--failed"}`}
    >
      <div className="benchmark-result-card__head">
        <span className="benchmark-result-card__id">{row.sample_id}</span>
        <Badge variant={row.passed ? "success" : "danger"}>{row.passed ? "通过" : "未通过"}</Badge>
        <span className="benchmark-result-card__latency">{formatLatency(latencyMs)}</span>
      </div>
      <p className="benchmark-result-card__question">{row.question}</p>
      <div className="benchmark-result-card__meta">
        <div className="benchmark-result-card__meta-item">
          <span className="benchmark-result-card__meta-label">期望意图</span>
          <span className="benchmark-result-card__intent">{formatIntent(row.expected_intent)}</span>
        </div>
        <div className="benchmark-result-card__meta-item">
          <span className="benchmark-result-card__meta-label">预测意图</span>
          <span
            className={`benchmark-result-card__intent${intentMismatch ? " benchmark-result-card__intent--mismatch" : ""}`}
          >
            {formatIntent(row.predicted_intent)}
          </span>
        </div>
      </div>
      {failureReasons.length > 0 ? (
        <div className="benchmark-result-card__failures">
          <span className="benchmark-result-card__meta-label">未通过原因</span>
          <ul className="benchmark-result-card__failure-list">
            {failureReasons.map(({ code, label }) => (
              <li key={code}>{label}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {tools.length > 0 ? (
        <div className="benchmark-result-card__tools">
          {tools.map((tool) => (
            <span key={tool} className="benchmark-tool-tag" title={tool}>
              {formatToolName(tool)}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function MetricCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className={`metric-card${highlight ? " metric-card--highlight" : ""}`}>
      <div className="metric-card__label">{label}</div>
      <div className="metric-card__value">{value}</div>
    </div>
  );
}
