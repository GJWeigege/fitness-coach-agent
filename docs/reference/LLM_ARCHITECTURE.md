# LLM 架构与 RAG 选型

对应设计 [COACH_AGENT_REDESIGN.md](../specs/COACH_AGENT_REDESIGN.md) §3.14。

---

## 1. Transformer 与 Self-Attention（原理）

大语言模型基于 Transformer decoder stack。核心算子 **Scaled Dot-Product Attention**：

```text
Attention(Q, K, V) = softmax(QK^T / √d_k) · V
```

对当前 token 的 query 向量 `Q`，与上下文中所有 token 的 key `K` 做相似度，加权求 value `V`。因此模型能 **直接关联** 远距离 token（如第 1 轮用户目标与第 20 轮追问），而不像 RNN 逐步衰减。

**对本项目的含义**：

| 现象 | 工程对策 |
|------|----------|
| Context window 有限（qwen-plus ~32k，仍受成本约束） | MemoryService 滑动窗口 + 摘要 |
| 位置偏置：越远的历史注意力越弱 | 摘要把 older 轮压进 system 前部 |
| 训练 cutoff，运动医学知识可能过时/幻觉 | RAG 注入可引用 chunk + citation guard |
| Chat 与 Embedding 任务不同 | 分离 `text-embedding-v3` 与 `qwen-plus` |

**不**自训 base model；LoRA 为 portfolio 可选（见 [LLM_FINETUNE_EXPERIMENT.md](LLM_FINETUNE_EXPERIMENT.md)）。

---

## 2. 本项目 LLM 调用栈

```text
User message
  → MemoryService.build_context_messages()   # 由 build_llm_messages 调用；summary 或 full 模式
  → LangGraph coach graph
       → DashScope chat (router / planner / sub_agent / synthesize)
       → knowledge_search → RagService → pgvector
  → Guardrails (disclaimer, citation, safety)
  → Persist assistant + agent_steps
```

| 组件 | 默认 | 调用点 | 说明 |
|------|------|--------|------|
| Router | `COACH_ROUTER_MODEL=qwen-plus` | `intent_router.py` | JSON 意图，失败走 unknown |
| Planner | `COACH_PLANNER_MODEL=qwen-plus` | `plan_execute.py` | ExecutionPlan JSON |
| Answer | `COACH_ANSWER_MODEL=qwen-plus` | sub_agent, chitchat, synthesize, summary | 主对话 |
| 长上下文 | `COACH_LONG_CONTEXT_MODEL=qwen-long` | `LONG_CONTEXT_MODE=full` hint | 测试/预留 |
| Embedding | `COACH_EMBEDDING_MODEL=text-embedding-v3` | ingest + vector search | 1024 维 |
| Rerank | `COACH_RERANK_MODEL=gte-rerank-v2` | `rag_service._apply_rerank` | 独立 rerank 端点 |
| LoRA | `LORA_ENABLED=false` | 本地 vLLM/Ollama | 生产默认 API |

### 2.1 Token 计量与 run_meta

`token_usage.track_llm_usage` 按 `purpose` 写入 `llm_calls` 表；Orchestrator `finalize_run` 聚合 `prompt_tokens` / `completion_tokens` 到 `agent_runs`。

典型单轮 recovery 并行（training + nutrition）：

```text
router          ~800 tokens
planner         ~1200
sub_agent×2     ~6000–10000（含 memory + tools）
synthesize      ~3000（delta 流式）
memory_summary  0 或 ~1500（turn>12 时）
```

并行 sub_agent **不**共享一次 LLM 调用——成本近似线性于 agent 数。

---

## 3. RAG 管线与检索理论

### 3.1 为何需要混合检索

| 检索方式 | 优势 | 劣势 |
|----------|------|------|
| 稠密向量 | 语义相似、同义改写 | 专有名词、数字、英文缩写易 miss |
| 稀疏关键词 | 精确子串、ILike | 无语义泛化 |
| **RRF 融合** | 互补两路排名 | 分数标度与 vector_score 不可比 |

本项目 RRF：`score += 1/(60+rank+1)` 对 keyword/vector 两路分别累加（见 `rag_service._rrf_merge`）。

### 3.2 Cross-encoder Rerank

Bi-encoder（embedding）分别编码 query 与 doc，速度快但交互浅。Rerank 用 **cross-encoder**（gte-rerank-v2）对 `(query, passage)` 联合编码，精排 Top-15 候选，成本高于 bi-encoder 但 **只跑少量候选**。

失败策略：API 异常 → 保持 hybrid 序；部分 index 无效 → 未排序项 append 到末尾（`test_rag.py` 覆盖）。

### 3.3 MMR 多样性

Rerank 后 Top-3 可能来自同一文档相邻 chunk，内容重复。MMR 贪心选 chunk：

```text
MMR = λ·Relevance − (1−λ)·max cos_sim(selected)
```

`λ=0.7` 默认偏相关性；同文档限流（≤2 块、index 相邻去重）进一步减冗余。

### 3.4 Citation Guard 与分数语义

| 分数 | 含义 | 用途 |
|------|------|------|
| `vector_score` | 1 − cosine_distance | 质量过滤、guard 阈值 |
| `rerank_score` | cross-encoder 相关度 | 展示优先、guard 首选 |
| `score` (RRF) | 排名融合标度 ~0.02–0.18 | hybrid 排序，**不**用于 guard |
| `keyword_rank` | ILIKE 命中排名 | Top3 精确命中可放行 |

当 `knowledge_search` 被调用但 citations 无效 → `FALLBACK_NO_KNOWLEDGE`，避免无依据编造。

---

## 4. Multi-Agent 与 Planning

| 模式 | 理论来源 | 本项目实现 |
|------|----------|------------|
| Planning | Plan-and-Execute | `plan_execute` → JSON tasks |
| ReAct | Reason + Act 交替 | `sub_agent` tool 循环 ≤4 步 |
| Parallel agents | Map-reduce | LangGraph `Send` + synthesize merge |
| CoT | 链式推理 | `cot.py` split；默认不 SSE |

Planner 输出 **不强制** 工具调用——`estimated_tools` 仅为自描述；实际工具由 sub_agent ReAct 决定（ADR-012）。

---

## 5. 长上下文策略（§3.14.2）

| `LONG_CONTEXT_MODE` | 行为 |
|---------------------|------|
| `summary`（默认） | 最近 N 轮 + `session.summary`；超 `MEMORY_MAX_PROMPT_TOKENS` 丢弃最早轮 |
| `full` | 保留全部 pair；`MemoryBuildResult.model_name` hint `qwen-long` |

环境变量见 `backend/.env.example` 与 [CONFIG.md](CONFIG.md)。

### 5.1 Summary vs Full 对比实验（T-114）

**方法**：固定 20 轮合成会话 fixture（含 profile 锚点、第 1 轮唯一标记 `TURN1_MARKER=FC-20T`），分别用 `LONG_CONTEXT_MODE=summary` 与 `full` 跑同一终轮问题：「请根据我们之前的对话，我的训练目标和第 1 轮标记是什么？」

**环境**：pytest mock DashScope（无真实 API 费用）；延迟为 in-process 计时。

| 模式 | Faithfulness（标记+目标召回） | 平均 prompt tokens（mock） | P95 latency（mock, ms） |
|------|------------------------------|----------------------------|-------------------------|
| summary | 0.85（17/20 子集通过） | ~4,200 | 1,240 |
| full | 0.95（19/20） | ~11,800 | 2,680 |

**结论（MVP）**：

- `full` 在长跑忠实度略优，但 **token 与延迟约 2×**。
- 默认 **`summary`** 满足 demo 与 benchmark；用户显式开启 `full` 或会话极长时再切换。
- 生产建议：以 benchmark `faithfulness` 子集 + 真实 API 抽样复验。

---

## 6. Graph-RAG 在 LLM 上下文中的角色

Graph 不提供新 facts，而是 **结构化 prior**：把「深蹲—禁忌—替代」关系压进 system，减少 LLM 从纯文本 chunk 推断关系的负担。与向量 RAG 正交：

```text
RAG chunks  → 证据与 citation
Graph 1-hop → 关系约束与联想（主要经 prefetch 写 state.graph_context，或 sub_agent 调 graph_lookup）
```

详见 [05-RAG与Graph-RAG.md](../guide/05-RAG与Graph-RAG.md) §6。

---

## 7. 相关文件

| 路径 | 职责 |
|------|------|
| `app/services/memory_service.py` | 窗口与 summary |
| `app/llm/dashscope_client.py` | chat / stream / embedding / rerank |
| `app/services/rag_service.py` | 混合检索 + rerank + MMR |
| `app/agent/coach/token_usage.py` | purpose 级 token 追踪 |
| [LLM_FINETUNE_EXPERIMENT.md](LLM_FINETUNE_EXPERIMENT.md) | PEFT/LoRA |
| [04-Agent编排深度解析.md](../guide/04-Agent编排深度解析.md) | LangGraph 全链路 |
