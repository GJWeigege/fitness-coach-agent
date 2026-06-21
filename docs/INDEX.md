# Fitness Coach Agent — 文档总导航

> **目标读者**：想深入学习本项目、准备面试、或 onboarding 的开发者  
> **语言**：中文为主；README Quick Start 为英文  
> **最后对齐代码**：仓库 `backend/app/` + `frontend/src/`（2026-06-21）  
> **深度章节**：guide/04 §2.1 Send 并行、§4.4 SSE 桥；guide/05 §6 Graph-RAG；guide/06 §8 记忆示例；reference/LLM_ARCHITECTURE 检索理论

---

## 1. 项目是什么

**Fitness Coach Agent** 是一个多运动健康领域的 AI Coach 系统：基于 **LangGraph Multi-Agent** 编排，结合 **Hybrid RAG + Graph RAG**、**7 个领域工具**、**SSE 流式对话** 与 **Benchmark 评测**，提供训练计划、营养建议、安全禁忌检查等个性化服务。

技术栈：**FastAPI + async SQLAlchemy + pgvector + LangGraph + React 19 + Vite + DashScope Qwen**。

**明确不做**：客服/handoff/工单、Neo4j 集群、HIPAA 级合规、移动端/IoT、自训 base model。

---

## 2. 三条阅读路径

### 路径 A — 30 分钟速览

适合：第一次 clone、面试前快速复习

1. [guide/01-项目概览与边界.md](guide/01-项目概览与边界.md)
2. [guide/03-系统架构与分层.md](guide/03-系统架构与分层.md) — 重点看 ChatService / Orchestrator 边界
3. [guide/04-Agent编排深度解析.md](guide/04-Agent编排深度解析.md) — § 全链路时序
4. [interview/CHEATSHEET.md](interview/CHEATSHEET.md)

### 路径 B — 系统深度学习（推荐，6–8 小时）

按序号阅读 `guide/` 全部 12 章：

| # | 文档 | 主题 |
|---|------|------|
| 01 | [项目概览与边界](guide/01-项目概览与边界.md) | 定位、边界、仓库结构 |
| 02 | [技术栈全解](guide/02-技术栈全解.md) | 选型与替代方案 |
| 03 | [系统架构与分层](guide/03-系统架构与分层.md) | 前后端分层、数据模型 |
| 04 | [Agent编排深度解析](guide/04-Agent编排深度解析.md) | **LangGraph 全图、Send 并行、ReAct、SSE 桥** |
| 05 | [RAG与Graph-RAG](guide/05-RAG与Graph-RAG.md) | **混合检索、MMR、Graph linking** |
| 06 | [记忆与长上下文](guide/06-记忆与长上下文.md) | summary vs full、15 轮示例 |
| 07 | [工具系统详解](guide/07-工具系统详解.md) | 7 工具逐一 |
| 08 | [前端与SSE](guide/08-前端与SSE.md) | replace/delta 契约 |
| 09 | [评测与观测](guide/09-评测与观测.md) | benchmark、timeline |
| 10 | [安全护栏与RBAC](guide/10-安全护栏与RBAC.md) | guardrails、三角色 |
| 11 | [代码导读-后端](guide/11-代码导读-后端关键路径.md) | 阅读顺序、测试地图 |
| 12 | [代码导读-前端](guide/12-代码导读-前端关键路径.md) | 路由、hooks |

### 路径 C — 面试突击（约 2 小时）

1. [interview/PITCH-5min.md](interview/PITCH-5min.md) — 熟读口述稿
2. [interview/FAQ.md](interview/FAQ.md) — 按主题刷 62 题
3. 薄弱章节回读对应 `guide/` + 章末「常见追问」
4. [decisions/INDEX.md](decisions/INDEX.md) — 过 ADR 标题与「面试一句话」

---

## 3. 文档类型说明

| 目录 | 用途 | 何时读 |
|------|------|--------|
| **guide/** | 叙事式深度学习：Why + How + 代码锚点 | 系统学习、面试准备 |
| **reference/** | 契约/速查：SSE、配置、验收、HA | 开发时查阅 |
| **decisions/** | ADR 关键决策及原因 | 回答「为什么这样设计」 |
| **interview/** | 口述稿、FAQ、一页纸速查 | 面试前 1–2 天 |
| **specs/** | 原始设计规格与任务清单 | 对照验收、查 § 节号；**运行时默认值以 `backend/app/core/config.py` 为准** |

---

## 4. 速查表

| 概念 | Primary 代码 | 文档 |
|------|-------------|------|
| 聊天入口 | `backend/app/services/chat_service.py` | guide/03, 11 |
| LangGraph 图 | `backend/app/agent/coach/graph.py` | guide/04 |
| 状态定义 | `backend/app/agent/coach/state.py` | guide/04 |
| 并行分发 | `backend/app/agent/coach/nodes/dispatch_sub_agents.py` | guide/04 |
| sub_agent ReAct | `backend/app/agent/coach/nodes/sub_agent.py` | guide/04 |
| 混合检索 | `backend/app/services/rag_service.py` | guide/05 |
| 记忆 | `backend/app/services/memory_service.py` | guide/06 |
| 7 工具 | `backend/app/agent/tools/` | guide/07 |
| SSE 桥接 | `backend/app/agent/coach/orchestrator.py` | guide/08, reference/AGENT_SSE |
| 前端 SSE | `frontend/src/hooks/useSessions.ts` | guide/08, 12 |
| 权限 | `backend/app/auth/permissions.py` | guide/10 |
| 数据模型 | `backend/app/db/models.py` | guide/03 |
| 配置 | `backend/app/core/config.py` | reference/CONFIG |
| Benchmark | `backend/app/services/benchmark_runner.py` | guide/09 |

---

## 5. 测试索引（49 个测试文件）

| 模块 | 测试文件 |
|------|----------|
| Chat / SSE | `test_chat_stream.py`, `test_sse_bridge.py`, `test_chat_sessions.py` |
| Agent 图 | `test_coach_graph.py`, `test_plan_execute.py`, `test_sub_agent_react.py` |
| 并行 / 恢复 | `test_parallel_recovery.py`, `test_recovery_serial_fallback.py` |
| RAG | `test_rag.py`, `test_ingest.py`, `test_seed_knowledge.py` |
| Graph | `test_graph.py`, `test_graph_context.py` |
| Memory | `test_memory.py`, `test_build_llm_messages.py`, `test_long_context_mode.py` |
| Tools | `test_coach_tools.py`, `test_registry.py` |
| Guardrails | `test_guardrails.py`, `test_safety_review.py`, `test_apply_guardrails_node.py` |
| Benchmark | `test_benchmark.py`, `test_benchmark_api.py`, `test_faithfulness_judge.py` |
| Auth / RBAC | `test_auth.py`, `test_login_lockout.py`, `test_rate_limit.py` |
| Observability | `test_obs_svc.py`, `test_observability_api.py`, `test_metrics.py` |

运行：`cd backend && pytest -q`

---

## 6. 交叉引用

| guide 章 | specs 节 | reference | decisions |
|----------|----------|-----------|-----------|
| 04 Agent | specs/COACH_AGENT_REDESIGN §3.4 | AGENT_SSE | 001, 002, 010, 012 |
| 05 RAG | §3 RAG | LLM_ARCHITECTURE | 004, 005 |
| 06 Memory | §3.14 | LLM_ARCHITECTURE | 006 |
| 08 SSE | §3.6 | AGENT_SSE | 003 |
| 09 Benchmark | 任务清单 | COACH_ACCEPTANCE | — |
| 10 安全 | §安全 | — | 009 |

---

## 7. 外部链接

- 根目录 [README.md](../README.md) — Quick Start（英文）
- OpenAPI：http://localhost:8000/docs（本地启动后）
