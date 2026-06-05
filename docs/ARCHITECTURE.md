# 项目架构说明

## 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React + Vite + pnpm)           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ Contexts │  │  Hooks   │  │  Pages   │  │  API Layer  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
│       └─────────────┴───────────────┴───────────────┘       │
└───────────────────────────────┬─────────────────────────────┘
                                │ REST + SSE
┌───────────────────────────────▼─────────────────────────────┐
│                   Backend (FastAPI + async SQLAlchemy)       │
│  ┌────────┐  ┌──────────┐  ┌────────┐  ┌──────┐  ┌────────┐ │
│  │  API   │→ │ Services │→ │  DB    │  │ LLM  │  │ Auth   │ │
│  └────────┘  └──────────┘  └────────┘  └──────┘  └────────┘ │
│         agent/coach/ (LangGraph) + agent/tools/              │
└───────────────────────────────┬─────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │ PostgreSQL + pgvector │
                    └───────────────────────┘
```

## 前端分层

| 层级 | 目录 | 职责 |
|------|------|------|
| 入口 | `src/main.tsx`, `App.tsx` | 挂载、Provider |
| 上下文 | `src/contexts/` | 认证、权限、全局错误 |
| 钩子 | `src/hooks/` | 会话、知识库、用户 |
| 页面 | `src/pages/` | Chat、Profile、Knowledge、AgentRuns、Benchmark、Users |
| 布局 | `src/layouts/`, `components/layout/` | 侧栏 RBAC |
| 组件 | `src/components/chat/`, `ui/` | 聊天气泡、SSE replace/delta |
| API | `src/api/` | HTTP + SSE 封装 |
| 样式 | `src/styles/` | CSS 变量设计系统 |

### 聊天数据流

```text
ChatInput → useSessions.sendMessage()
         → api/chat.streamMessage() [SSE: step | replace | delta | done]
         → ChatWindow → MessageBubble
```

SSE 契约见 [AGENT_SSE.md](AGENT_SSE.md)：`done` 仅在 assistant 消息入库后发出。

## 后端分层

| 层级 | 目录 | 职责 |
|------|------|------|
| 入口 | `app/main.py` | lifespan（seed）、路由、CORS |
| API | `app/api/` | auth, chat, profile, knowledge, observability, benchmark |
| Schemas | `app/schemas/` | Pydantic 模型 |
| Services | `app/services/` | chat, rag, memory, ingest, graph, benchmark |
| Agent | `app/agent/coach/` | LangGraph 图、orchestrator、nodes |
| Tools | `app/agent/tools/` | 7 个 coach 工具 + registry |
| Auth | `app/auth/` | RBAC、`require_permissions` |
| LLM | `app/llm/` | DashScope 客户端 |
| Prompts | `app/prompts/coach/` | planner、CoT、子 agent |

### Coach Agent 图（简化）

```text
route_intent → plan_execute → dispatch_sub_agents (Send 并行)
            → sub_agent ReAct → synthesize → apply_guardrails → finalize_run
```

### RAG 流程

```text
上传/seed → ingest_service（分块 + embedding）→ knowledge_chunks

提问 → knowledge_search / rag_service（混合检索）
     → 注入 sub_agent prompt → citations 写入 message
```

### 异步任务（202 + BackgroundTasks）

| 接口 | 后台任务 |
|------|----------|
| `POST /knowledge/upload` | 分块索引 |
| `POST /knowledge/documents/{id}/reindex` | 重建向量 |
| `POST /benchmark/runs` | 评测集跑分 |

## 权限模型（RBAC）

| 角色 | 典型权限 |
|------|----------|
| user | 聊天、本人会话、profile、feedback |
| kb_editor | + knowledge read/write/reindex |
| admin | + 用户管理、observability、benchmark |

演示账号见根目录 [README.md](../README.md)。

## 运行与测试

```bash
# 基础设施
docker compose up -d

# 后端
cd backend && pip install -r requirements.txt
alembic upgrade head
pytest -q
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend && pnpm install && pnpm run build
```

## 扩展建议

- 多 worker 部署时注意 SSE sticky session（见 [COACH_HA.md](COACH_HA.md)）
- BackgroundTasks → Celery 若需跨实例任务
- Benchmark 数据集扩至 80+ 条以满足验收阈值

**不包含**：handoff、ticket、客服业务工具。
