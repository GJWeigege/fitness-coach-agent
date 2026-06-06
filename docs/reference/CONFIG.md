# 环境变量配置全表

> 来源：`backend/app/core/config.py`（Settings）  
> 配置文件：`backend/.env`（从 `.env.example` 复制）  
> 阅读时间：10 min | 关联：[guide/02-技术栈全解.md](../guide/02-技术栈全解.md)

---

## 必填项

| 变量 | 说明 |
|------|------|
| `DASHSCOPE_API_KEY` | DashScope API Key；chat、embedding、agent 均依赖 |
| `AUTH_SECRET_KEY` | JWT 签名密钥；**production/staging 必须 ≥32 字符且非默认值** |

---

## App / 运行环境

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_NAME` | `fitness-coach-agent` | 应用名 |
| `APP_ENV` | `dev` | `dev` / `test` / `staging` / `production` |
| `APP_HOST` | `0.0.0.0` | uvicorn bind |
| `APP_PORT` | `8000` | uvicorn port |
| `LOG_LEVEL` | `INFO` | 日志级别 |

---

## Database

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/fitness_coach` | async SQLAlchemy DSN |
| `DB_POOL_SIZE` | `10` | 连接池大小 |
| `DB_MAX_OVERFLOW` | `20` | 连接池 overflow |

---

## LLM / DashScope

| 变量 | 默认值 | 说明 | 调优建议 |
|------|--------|------|----------|
| `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI 兼容端点 | — |
| `COACH_ROUTER_MODEL` | `qwen-plus` | route_intent | 可换更小模型降本 |
| `COACH_ANSWER_MODEL` | `qwen-plus` | sub_agent / synthesize | 质量与成本平衡 |
| `COACH_PLANNER_MODEL` | `qwen-plus` | plan_execute | JSON plan 需稳定输出 |
| `COACH_EMBEDDING_MODEL` | `text-embedding-v3` | RAG embedding | 与 `EMBEDDING_DIM` 一致 |
| `COACH_LONG_CONTEXT_MODEL` | `qwen-long` | `LONG_CONTEXT_MODE=full` 时 | token 成本更高 |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60` | 单次 LLM 超时 | 长回答可调大 |
| `LLM_MAX_RETRIES` | `1` | 失败重试 | 生产可设 2 |

---

## RAG

| 变量 | 默认值 | 说明 | 调优建议 |
|------|--------|------|----------|
| `EMBEDDING_DIM` | `1024` | 向量维度 | 与 embedding 模型一致 |
| `RAG_TOP_K` | `4` | 最终返回 chunk 数 | 增大→更多上下文、更高成本 |
| `RAG_HYBRID_ENABLED` | `true` | 向量+关键词 RRF | 中文建议保持 true |
| `RAG_KEYWORD_TOP_K` | `8` | 关键词召回上限 | — |
| `RAG_SCORE_THRESHOLD` | `0.35` | 最低相关分 | 降低→更多噪声；升高→漏召回 |
| `RAG_SCORE_FLOOR` | `0.01` | 分数下限 | — |
| `RAG_SCORE_MIN_GAP` | `0.004` | 相邻 chunk 最小分差 | — |
| `USE_RAG_DEFAULT` | `true` | Chat 默认启用 RAG | 前端可 per-request 覆盖 |
| `GRAPH_RAG_ENABLED` | `true` | 注册 graph_lookup 工具 | false 则纯 RAG |

---

## Agent / LangGraph

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SUB_AGENT_MAX_TOOL_STEPS` | `4` | sub_agent ReAct 最大工具步数 |
| `MAX_SUB_AGENTS_PER_TURN` | `2` | 每轮最多 sub_agent 数 |
| `PARALLEL_SUB_AGENTS_ENABLED` | `true` | LangGraph Send 并行 |
| `COT_ENABLED` | `true` | planner/sub_agent CoT |
| `COT_SSE_ENABLED` | `false` | 是否 SSE 推送 reasoning |
| `AGENT_ENABLE_THINKING_STEPS` | `true` | SSE step/tool 事件 |
| `PROFILE_REQUIRED_FOR_PLAN` | `false` | 无 profile 是否阻断 plan |

---

## Memory / 长上下文

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LONG_CONTEXT_MODE` | `summary` | `summary` \| `full` |
| `LORA_ENABLED` | `false` | 本地 LoRA（实验） |
| `LORA_ADAPTER_PATH` | `""` | LoRA 适配器路径 |
| `MEMORY_MAX_TURNS` | `8` | 滑动窗口轮数 |
| `MEMORY_MAX_PROMPT_TOKENS` | `12000` | prompt token 硬上限 |
| `MEMORY_SUMMARY_TRIGGER_TURNS` | `12` | 触发滚动摘要 |
| `MEMORY_SUMMARY_MAX_CHARS` | `500` | 摘要最大字符 |
| `MEMORY_MAX_USER_CHARS` | `8000` | 单条 user 消息上限 |

---

## Ingest / 知识库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `INGEST_CHUNK_SIZE` | `800` | 分块大小（字符） |
| `INGEST_CHUNK_OVERLAP` | `120` | 分块重叠 |
| `UPLOAD_DIR` | `backend/data/uploads` | 上传目录 |
| `MAX_UPLOAD_BYTES` | `10485760` | 10MB 上传限制 |

---

## Benchmark

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BENCHMARK_CONCURRENCY` | `2` | 评测并发 |
| `BENCHMARK_FAITHFULNESS_USE_LLM` | `false` | faithfulness 是否用 LLM judge |
| `BENCHMARK_RECONCILE_STALE_RUNS` | `true` | 启动时 reconcile 卡住 run |

---

## Auth / Security

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `720` | JWT 有效期（12h） |
| `CORS_ORIGINS` | `http://localhost:5173,...` | 逗号分隔；**部署不能为空** |
| `TRUSTED_PROXIES` | `""` | 反向代理 IP |
| `RATE_LIMIT_MAX_KEYS` | `10000` | 限流 key 上限 |
| `LOGIN_LOCKOUT_MAX_ATTEMPTS` | `5` | 登录失败锁定次数 |
| `LOGIN_LOCKOUT_WINDOW_SECONDS` | `900` | 锁定窗口（15min） |

---

## 部署校验

`APP_ENV=production` 或 `staging` 时：

- `AUTH_SECRET_KEY` 不得为内置弱默认值，长度 ≥32
- `CORS_ORIGINS` 不得为空

见 `Settings.validate_auth_secret_for_env()` / `validate_cors_origins_for_env()`。

---

## 延伸阅读

- [guide/05-RAG与Graph-RAG.md](../guide/05-RAG与Graph-RAG.md) — RAG 参数调优
- [guide/06-记忆与长上下文.md](../guide/06-记忆与长上下文.md) — summary vs full
- [specs/COACH_AGENT_REDESIGN.md](../specs/COACH_AGENT_REDESIGN.md) §3.2 — 原始配置表
