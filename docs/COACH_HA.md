# Coach Agent 高可用与容量规划（MVP 笔记）

本文档记录 **fitness-coach-agent** 在单机 MVP 之上的 HA / 扩容要点，便于面试 demo 与后续生产化。

## 1. 组件拓扑

```text
                    ┌─────────────┐
  Browser ─────────►│  Vite SPA   │
                    └──────┬──────┘
                           │ REST + SSE
                    ┌──────▼──────┐
                    │  FastAPI    │  ← 无状态，可水平扩展
                    │  (uvicorn)  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │ PostgreSQL  │
                    │ + pgvector  │
                    └─────────────┘
                           │
                    ┌──────▼──────┐
                    │  DashScope  │  （外部 LLM / Embedding API）
                    └─────────────┘
```

**无状态层**：FastAPI 进程不保存会话；JWT + DB 即可多副本部署。SSE 长连接需 **sticky session** 或同 pod 亲和（见 §3）。

## 2. 数据库 HA

| 层级 | MVP | 生产建议 |
|------|-----|----------|
| Postgres | `docker compose` 单实例 | 托管 RDS / Cloud SQL + 自动备份 |
| pgvector | 同库 | 主从只读副本可做检索只读（需应用层读写分离） |
| 连接池 | SQLAlchemy async pool | 按 `workers × 并发` 调 `DB_POOL_SIZE` |

故障切换：应用重连 + 健康检查 `/health`；迁移用 Alembic 单向前进。

## 3. 应用层 HA

### 3.1 多 Worker

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

- **REST** 请求任意 worker 均可处理。
- **SSE `/chat/stream`**：客户端与单个 worker 保持连接；负载均衡需 **IP Hash / cookie sticky**，否则断流。

### 3.2 异步任务

以下接口返回 **202**，由 FastAPI `BackgroundTasks` 在响应后执行（单进程内；多 worker 时各 worker 独立队列）：

| 接口 | 任务 |
|------|------|
| `POST /knowledge/upload` | 分块 + embedding 入库 |
| `POST /knowledge/documents/{id}/reindex` | 重建向量索引 |
| `POST /benchmark/runs` | 评测集批量跑分 |

生产环境若需跨实例任务队列，可替换为 Celery / ARQ + Redis，接口契约保持不变。

### 3.3 限流与熔断

- `core/rate_limit.py`：知识库 upload/reindex、登录 lockout。
- Agent 降级：`status=degraded`、ReAct 步数耗尽走 RAG 单跳 + disclaimer（见设计 §3.11）。

## 4. 外部依赖

| 依赖 | 风险 | 缓解 |
|------|------|------|
| DashScope API | 超时 / 429 | `LLM_MAX_RETRIES`、超时 fallback、静态安全模板 |
| Embedding | 与 chat 同 vendor | 批量 reindex 用 BackgroundTasks 削峰 |

## 5. 负载测试

使用 k6 脚本压测 SSE 聊天：

```bash
# 先登录获取 TOKEN
k6 run scripts/load/chat_stream.js \
  -e BASE_URL=http://localhost:8000 \
  -e TOKEN=<jwt> \
  -e VUS=5 \
  -e DURATION=60s
```

**观察指标**：

- `http_req_failed` < 5%
- P95 端到端延迟（含 LLM）— MVP 目标 ≤ 8s（与 benchmark `latency_p95_ms` 一致）
- Postgres 连接数、CPU

## 6. 部署检查清单

- [ ] `APP_ENV=production`，强随机 `AUTH_SECRET_KEY`（≥32 字符）
- [ ] `CORS_ORIGINS` 限定前端域名
- [ ] Postgres 持久卷 + 定期备份
- [ ] 日志聚合（request `trace_id` 已注入 middleware）
- [ ] 健康探针：`GET /health`
- [ ] 密钥不入库（`.env` / Secret Manager）

## 7. 已知 MVP 限制

- BackgroundTasks 不跨 worker 共享；benchmark 长跑占用 worker 线程。
- LoRA 推理仅本地 vLLM/Ollama（`LORA_ENABLED=false` 默认走 API）。
- 无 OpenTelemetry 全链路（Backlog）。

---

**维护**：与 `docs/ARCHITECTURE.md`、`docs/COACH_AGENT_REDESIGN.md` §6 对齐。
