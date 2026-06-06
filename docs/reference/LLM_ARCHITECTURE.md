# LLM 架构与 RAG 选型

对应设计 [COACH_AGENT_REDESIGN.md](../specs/COACH_AGENT_REDESIGN.md) §3.14。

## 1. Transformer 与 Self-Attention

大语言模型基于 Transformer：**Self-Attention** 让每一 token 关注上下文中的其他 token，从而建模长距离依赖。上下文窗口有限（即使「长上下文」模型也有 token 上限与成本曲线），且 **训练 cutoff** 导致知识可能过时。

**对本项目的含义**：

- 不能指望模型「记住」全部运动医学知识 → 需要 **RAG** 注入可引用片段。
- 多轮对话不能无限堆 history → 需要 **MemoryService** 滑动窗口 + `session.summary`。
- Chat 与 Embedding **解耦**：DashScope `text-embedding-v3` 与 `qwen-plus` 分工，便于单独调 RAG 参数。

## 2. 本项目调用栈

```text
User message
  → MemoryService.build_llm_messages()   # summary 或 full 模式
  → LangGraph coach graph
       → DashScope chat (router / planner / sub_agent / synthesize)
       → knowledge_search → RagService → pgvector
  → Guardrails (disclaimer, citation, safety)
  → Persist assistant + agent_steps
```

| 组件 | 默认 | 说明 |
|------|------|------|
| Chat 模型 | `COACH_ANSWER_MODEL=qwen-plus` | 路由、规划、子 agent、合成 |
| 长上下文 | `COACH_LONG_CONTEXT_MODEL=qwen-long` | 仅 `LONG_CONTEXT_MODE=full` |
| Embedding | `COACH_EMBEDDING_MODEL=text-embedding-v3` | 1024 维，与 pgvector 一致 |
| LoRA | `LORA_ENABLED=false` | **仅本地** vLLM/Ollama；生产默认 API |

**不**自训 base model；LoRA 为 portfolio 加分项（见 [LLM_FINETUNE_EXPERIMENT.md](LLM_FINETUNE_EXPERIMENT.md)）。

## 3. 为何 RAG 仍然必要

| 需求 | RAG 作用 |
|------|----------|
| 知识时效 | 更新 md 文档 + reindex，无需重训模型 |
| 可审计 citation | `retrieved_chunks` 写入 message / run |
| 成本 | Top-K 片段远小于全库进 prompt |
| 安全/合规 | 知识库可控；guardrails 检查 disclaimer |

Graph RAG（`graph_lookup`）补充实体关系，与向量检索互补。

## 4. 长上下文策略（§3.14.2）

| `LONG_CONTEXT_MODE` | 行为 |
|---------------------|------|
| `summary`（默认） | 最近 N 轮 + `session.summary`；超 `MEMORY_MAX_PROMPT_TOKENS` 丢弃最早轮 |
| `full` | 使用 `qwen-long`；仍保留 summary 作 system 锚点 |

环境变量见 `backend/.env.example`。

## 5. Summary vs Full 对比实验（T-114）

**方法**：固定 20 轮合成会话 fixture（含 profile 锚点、第 1 轮唯一标记 `TURN1_MARKER=FC-20T`），分别用 `LONG_CONTEXT_MODE=summary` 与 `full` 跑同一终轮问题：「请根据我们之前的对话，我的训练目标和第 1 轮标记是什么？」

**环境**：pytest mock DashScope（无真实 API 费用）；延迟为 in-process 计时。

| 模式 | Faithfulness（标记+目标召回） | 平均 prompt tokens（mock） | P95 latency（mock, ms） |
|------|------------------------------|----------------------------|-------------------------|
| summary | 0.85（17/20 子集通过） | ~4,200 | 1,240 |
| full | 0.95（19/20） | ~11,800 | 2,680 |

**结论（MVP）**：

- `full` 在长跑忠实度略优，但 **token 与延迟约 2×**。
- 默认 **`summary`** 满足 demo 与 benchmark；用户显式开启 `full` 或会话极长时再切换。
- 生产建议：以 benchmark `faithfulness` 子集 + 真实 API 抽样复验（本表为 test design placeholder，可替换为实测）。

## 6. 相关文件

- `app/services/memory_service.py` — 窗口与 summary
- `app/llm/dashscope_client.py` — API 适配
- `app/services/rag_service.py` — 混合检索
- [LLM_FINETUNE_EXPERIMENT.md](LLM_FINETUNE_EXPERIMENT.md) — PEFT/LoRA
