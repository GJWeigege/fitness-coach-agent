# 架构决策记录（ADR）索引

| ID | 标题 | 面试一句话 |
|----|------|-----------|
| [001](ADR-001-langgraph-without-langchain-adapter.md) | LangGraph 不用 LangChain ChatModel | 少一层抽象，mock DashScopeClient 即可单测 |
| [002](ADR-002-chatservice-orchestrator-split.md) | ChatService / Orchestrator 职责分离 | 消息事务与 agent 观测解耦，done 语义清晰 |
| [003](ADR-003-sse-replace-vs-delta.md) | synthesize 用 replace vs delta | 单 agent 整段 replace；多 agent 合并才 delta |
| [004](ADR-004-hybrid-rag-default.md) | 默认 Hybrid RAG | 中文 keyword + 向量 RRF 互补 |
| [005](ADR-005-graph-rag-as-supplement.md) | Graph 存 PG 非 Neo4j | MVP 运维简单，实体规模可控 |
| [006](ADR-006-long-context-summary-default.md) | 默认 summary 长上下文 | token/延迟约 half，faithfulness 85% 可接受 |
| [007](ADR-007-dashscope-api-production-lora-local.md) | 生产 API、LoRA 本地 | 稳定与成本；LoRA 为 portfolio 实验 |
| [008](ADR-008-background-tasks-not-celery.md) | BackgroundTasks 非 Celery | 单实例 MVP；HA doc 说明升级路径 |
| [009](ADR-009-jwt-rbac-three-roles.md) | JWT + 三角色 RBAC | demo 到 admin 观测/评测完整闭环 |
| [010](ADR-010-parallel-sub-agents-send.md) | LangGraph Send 并行 | 框架级 state merge，优于裸 gather |
| [011](ADR-011-cot-internal-not-sse-default.md) | CoT 默认不 SSE | 减带宽与推理泄露；入库可观测 |
| [012](ADR-012-persist-turn-noop-in-graph.md) | persist_turn 空节点 | 明确图不写 chat_messages |

关联 guide：[../guide/](../guide/) · 原始规格：[../specs/COACH_AGENT_REDESIGN.md](../specs/COACH_AGENT_REDESIGN.md)
