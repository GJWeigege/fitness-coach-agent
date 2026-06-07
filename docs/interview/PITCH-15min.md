# 15 分钟深度口述稿

> 前置：熟读 [PITCH-5min.md](PITCH-5min.md)  
> 本稿在 5 分钟版基础上展开原理、代码路径与 demo 话术

---

## Part 1 — 背景与动机（2 min）

### 为什么做

- JD / portfolio 需要展示：**Multi-Agent、Planning、RAG、Tool、Benchmark、系统工程**。
- 运动健康场景能自然组合：**个性化 profile、知识库、安全禁忌、训练记录**。
- **明确不做**客服 handoff、Neo4j 集群、自训 base model——边界清晰。

### 和 general ChatBot 差异

| 维度 | 套壳 | 本项目 |
|------|------|--------|
| 编排 | 单 prompt | LangGraph 状态图 + 并行 Send |
| 知识 | 模型内化 | Hybrid RAG + citation |
| 行动 | 无 | 7 tools ReAct |
| 质量 | 主观 | benchmark faithfulness |
| 排障 | 无 | agent_steps timeline |

---

## Part 2 — 架构深讲（4 min）

### 2.1 职责分离（必讲）

打开 `chat_service.py` 的 `stream_message`：

1. 存 user + commit  
2. `orchestrator.stream_turn` 转发 SSE，吞 `result`  
3. 存 assistant  
4. `maybe_update_summary`  
5. `finalize_run`  
6. `done`  

**追问防御**：「为什么图里 persist_turn 是空的？」→ ADR-012，边界文档化。

### 2.2 LangGraph 拓扑

讲 `graph.py` 条件边：chitchat / unknown / Send / serial_dispatch 四路。

### 2.3 CoachState reducer

并行时 `agent_outputs`、`tool_calls` 如何 merge——Annotated `merge_dicts` / `merge_lists`。

---

## Part 3 — RAG 深讲（3 min）

1. ingest：800/120 chunk，1024 维 embedding  
2. retrieve：vector + keyword → RRF k=60 → threshold 0.35  
3. citation 写入 `chat_messages.retrieved_chunks`  
4. Graph：`graph_lookup` 补充关系型 query  

**对比题**：「为什么不 Milvus？」→ 同库事务、MVP 运维、见 ADR-004/005。

---

## Part 4 — Live Demo 话术（5 min）

> 预录演示视频见 [demo-videos/](demo-videos/)（`pnpm --dir scripts/demo run record` 可重录）  
> 完整流程：Profile → Chat/Multi-Agent → Knowledge → Benchmark → Agent Runs

1. 登录 `coach_demo` / `Demo@123456`  
2. **Profile**：填写增肌目标、左膝旧伤、训练记录——说明个性化 tool 数据来源  
3. **Chat** 问：「我想增肌，膝盖有旧伤，请给训练和饮食建议。」  
4. 指 **AgentStepsPanel**：routing → planning → training_agent ∥ nutrition_agent → synthesizing  
5. 指 **citations** 气泡底部引用  
6. 切换 `admin_demo`，**Knowledge** 展示 seed 文档与「重建索引」  
7. **Benchmark** 打开历史 completed run，指 Intent / Citation / Faithfulness 指标  
8. **Agent Runs** 看 llm_calls token 与 step timeline  

---

## Part 5 — 评测与生产（2 min）

- benchmark jsonl、faithfulness markers  
- summary vs full 实验数据（85% vs 95%，token 2×）  
- 生产 gap：Celery、sticky SSE、benchmark 持续迭代——[COACH_HA](../reference/COACH_HA.md)

---

## Part 6 — Q&A 缓冲（1 min）

引导面试官选题：

- Agent / 并行 / Send  
- RAG / RRF / Graph  
- SSE / done 语义  
- 安全 / RBAC  

详细题见 [FAQ.md](FAQ.md)。

---

## JD 十条映射（备用）

1. Multi-Agent 并行 → Send  
2. Planning → plan_execute JSON  
3. CoT → cot_traces 入库  
4. 垂直领域 → 7 tools + seed 知识  
5. 个性化 → profile + macros  
6. Graph RAG → graph_lookup  
7. RAG+Tool → knowledge_search + ReAct  
8. Benchmark → runner + dashboard  
9. 系统工程 → SSE/RBAC/观测/49 tests  
10. LLM 深度 → summary/full + LoRA 脚本  
