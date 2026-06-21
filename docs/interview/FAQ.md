# 面试 FAQ（62 题 + 追问链）

> 配合 [guide/](../guide/) 各章「常见追问」使用  
> 标记 ★ 为高频题

---

## 主题 A — 项目整体（8 题）

### A1 ★ 用 30 秒介绍这个项目

LangGraph 多运动健康 Coach：并行 training/nutrition 子 Agent、Planning、Hybrid RAG、7 工具；FastAPI+pgvector+React SSE；含 benchmark 与全链路观测。

### A2 为什么选运动健康垂直领域？

能组合 RAG、Tool、profile、安全规则；比通用 Bot 更能展示 Multi-Agent 分工和可评测闭环。

### A3 ★ 和 ChatGPT 套壳区别？

有显式 Planning 图、并行 sub_agent、工具 ReAct、citation、agent_run 观测；不是单 prompt 直连。

### A4 ★ 技术难点 TOP3？

① ChatService/Orchestrator 分离 + done 语义；② 并行 Send 状态 merge；③ replace/delta SSE 契约。

### A5 重做会改什么？

更早引入 Celery；benchmark 样本持续扩充；E2E 测试；可选 Redis 限流。

### A6 生产化还差什么？

Celery、SSE sticky、监控告警、faithfulness 真实 API 抽样、样本扩容。见 COACH_HA。

### A7 solo 全栈怎么说？

我负责架构到实现：后端 Agent/RAG、前端 SSE、评测脚本、文档与 49 个测试。

### A8 如何证明 Agent 优于单 LLM？

Benchmark faithfulness；双域并行场景；tool 调用可审计；单 LLM 难稳定拆 task+调工具。

---

## 主题 B — Multi-Agent & LangGraph（18 题）

### B1 ★ LangGraph 是什么？

基于状态的有向图编排框架；节点是 async 函数；支持条件边、Send 并行、state reducer。

**追问链** → B2, B3

### B2 CoachState 怎么设计？

TypedDict + Annotated reducer：`agent_outputs`/`cot_traces` merge_dicts，`tool_calls` merge_lists。见 `state.py`。

### B3 ★ 并行 sub_agent 怎么实现？

`plan_execute` 产出 tasks → `route_after_plan_execute` 返回 `[Send("sub_agent", payload), ...]`。

**追问**：Send vs gather？→ LangGraph 框架 merge State，见 ADR-010。  
**追问**：一个失败？→ serial_dispatch / recovery 测试覆盖。

### B4 Send 和 asyncio.gather 区别？

Send 是一等公民，与 checkpoint/reducer 集成；gather 需手写 state 冲突与异常传播。

### B5 plan_execute 输出什么？

`ExecutionPlan`：tasks（agent+goal）、constraints、estimated_tools；chitchat 空 plan。

### B6 planner 输出非法 JSON？

`parse_and_validate_plan` 降级，从 active_agents 生成 fallback tasks；status=degraded。

### B7 ★ sub_agent ReAct 循环？

最多 4 步 `chat_stream_with_tools` → 执行 tool → 结果追加 messages → 直到无 tool 或上限。

### B8 training 和 nutrition agent 区别？

不同 system prompt 与 tool 倾向；同一 `sub_agent_node`，靠 `current_agent_key` 区分。

### B9 coach_chitchat 何时触发？

intent=chitchat；或 unknown 经 knowledge_prefetch；或无有效 plan tasks。

### B10 recovery 场景？

`route_intent` → recovery，`active_agents=[training,nutrition]`；planner/fallback 产出同 `parallel_group`（如 0）的双 task → `Send×2` 并行 sub_agent → synthesize LLM 合并。`PARALLEL_SUB_AGENTS_ENABLED=false` 时改 `serial_dispatch`。

### B11 serial_dispatch 是什么？

`PARALLEL_SUB_AGENTS_ENABLED=false` 且 tasks>1 时，顺序调用 `sub_agent_node` 并手动 merge outputs/tools/cot。

### B12 safety_review 和 synthesize 顺序？

先 safety_review 设 safety_blocked；再 synthesize 出 final_answer（或安全模板）。

### B13 如何加新 agent？

扩展 route/planner prompt agent 枚举；build_llm_messages 加 prompt；可选 tool 过滤。

### B14 MAX_SUB_AGENTS=2 原因？

控制 latency/token；benchmark 覆盖双域；API 并发成本。

### B15 并行 tool_calls 怎么 merge？

`merge_lists` reducer 追加各 Send 分支的 tool_calls。

### B16 agent_outputs 冲突？

key 为 agent 名（training/nutrition），不同 key 不冲突；同 key 后者覆盖（通常不会同 agent 并行）。

### B17 LangGraph 怎么调试？

agent_steps payload；LOG_LEVEL；test_coach_graph；admin AgentRuns timeline。

### B18 ★ persist_turn 为什么空？

ADR-012：文档化图不写 chat_messages；持久化在 ChatService。

---

## 主题 C — RAG & 知识（14 题）

### C1 ★ RAG 端到端流程？

upload/seed → chunk → embedding → retrieve(hybrid) → tool/sub_agent → citations → message JSONB。

### C2 为什么需要 RAG？

知识时效、citation 审计、成本、可控域；模型 cutoff 与幻觉。

### C3 ★ Hybrid 检索原理？

vector cosine + keyword ILIKE → RRF(k=60) → threshold → top_k。

**追问链样例**：

**Q**: 为什么不用纯向量？  
**A**: 中文术语 keyword 更稳。  
**↳ Q**: RRF 公式？  
**A**: score(d)=Σ 1/(60+rank+1)，rank 为 0-based。  
**↳ Q**: 怎么调 threshold？  
**A**: benchmark faithfulness vs 噪声 citation 率。

### C4 RRF 公式？

见 C3；k=60 为常用平滑常数。

### C5 score threshold 0.35 怎么定？

MVP 经验值 + benchmark 调优；过低噪声多，过高漏召回。

### C6 chunk 400/60 依据？

Markdown 优先按 `##` 小节；超长节内二次切分默认 400 字、重叠 60；改参数需 reindex。

### C7 embedding 1024 维？

DashScope text-embedding-v3 默认；与 pgvector 列维一致。

### C8 Graph RAG 解决什么？

实体关系查询（替代动作、禁忌关联）；补向量 structured gap。

### C9 Graph vs Neo4j？

PG 表 MVP 够用；免集群；ADR-005。

### C10 citation 可审计？

retrieved_chunks 存 message；retrieval_logs 存 query；run 可 replay。

### C11 幻觉怎么缓解？

RAG  grounding + threshold + guardrails + 规则 contraindication。

### C12 reindex 何时需要？

改 chunk 参数、换 embedding 模型、文档更新。

### C13 PDF 怎么处理？

pypdf 抽文本 → 同 ingest 流水线。

### C14 如何评估 RAG？

benchmark faithfulness；retrieval_logs 抽样；人工看 citation 相关性。

---

## 主题 D — Memory & LLM（8 题）

### D1 长上下文问题？

context 有限、成本曲线、早期细节丢失 → 窗口+摘要。

### D2 ★ summary vs full？

summary：8 轮+摘要，qwen-plus；full：qwen-long 全 history。faithfulness 85% vs 95%，token ~2×。

### D3 摘要何时触发？

`turn_count > 12` 且存在 older 对（超出最近 8 轮）；在 `_complete_turn_events` 里 **assistant 入库之前** 调用 `maybe_update_summary`。

### D4 MEMORY_MAX_TURNS=8？

控制 prompt 大小；与 summary 配合。

### D5 Transformer attention 简述？

每 token 加权关注上下文；长距离依赖；窗口有限 → 需 RAG/Memory。

### D6 chat 和 embedding 分开？

模型分工、独立调参、embedding 维数固定；换 chat 不必重嵌全库。

### D7 LoRA 和 RAG 关系？

正交；LoRA 改行为风格；RAG 注入知识；生产默认 API+RAG。

### D8 qwen-plus vs qwen-long？

plus 默认 chat；long 用于 full memory 模式，成本更高。

---

## 主题 E — 工程化 & SSE（10 题）

### E1 ★ 用户发消息全链路？

见 guide/03 七步 + guide/04 时序。

**追问链样例**：

**Q**: 全链路？  
**A**: 存 user → stream_turn SSE → summary（older）→ 存 assistant → finalize → done。  
**↳ Q**: 为何 graph 后存 assistant？  
**A**: final_answer 来自 CoachRunResult。  
**↳ Q**: done 谁发？  
**A**: 仅 ChatService，表示已入库。

### E2 SSE vs WebSocket？

单向推送足够；SSE 走 HTTP 同鉴权；实现简单。

### E3 ★ replace vs delta？

单 agent replace 整段；多 agent 合并 delta 流式；ADR-003。

### E4 done 谁发？为什么？

ChatService；语义 assistant 已 commit 且 finalize_run 完成。

### E5 SSE 中途失败？

yield error；assistant 不入库；user 已 commit。

### E6 多 worker SSE？

需 sticky session；否则连接漂移。COACH_HA。

### E7 事务边界？

user commit 在 graph 前；assistant commit 在 graph 后；run/steps 在 orchestrator。

### E8 BackgroundTasks 局限？

单进程内存队列；不跨 worker；重启丢失 → Celery。

### E9 49 测试怎么组织？

按 chat/graph/rag/memory/tool/benchmark/auth 分组；mock DashScope。

### E10 k6 测什么？

chat_stream.js SSE 压测 latency/错误率。

---

## 主题 F — 安全 & 权限（4 题）

### F1 RBAC 三角色？

user 聊天；kb_editor +知识库；admin +用户/观测/benchmark。

### F2 医疗免责？

guardrails disclaimer；safety 模板；非诊断声明。

### F3 prompt injection？

输出 sanitize；tool 权限；知识作 reference 非指令。

### F4 用户数据隔离？

session user_id 校验；JWT 身份；admin 才 read:all sessions。

---

## 使用建议

1. 先刷 ★ 题，再按薄弱主题回 guide  
2. 每题尝试 **30 秒口头答**，再展开追问链  
3. 结合 [CHEATSHEET.md](CHEATSHEET.md) 背数字与路径  
