# 5 分钟项目口述稿

> 适用：技术面开场「介绍一下这个项目」  
> 建议：配合 [CHEATSHEET.md](CHEATSHEET.md) 记忆数字与路径

---

## 【0:00–0:15】开场定位

我做的是 **Fitness Coach Agent**——多运动健康领域的 **Multi-Agent AI Coach**。用户通过 Web 聊天提问，系统能并行调用 **训练、营养** 等子 Agent，结合 **Hybrid RAG 知识库** 和 **7 个领域工具**，给出带引用、带安全护栏的个性化建议。技术栈是 **FastAPI + LangGraph + pgvector + React SSE**，LLM 用 **DashScope Qwen**。

---

## 【0:15–1:30】架构（指着三层讲）

整体分三层：

1. **前端 React**：`useSessions` 消费 SSE，处理 `replace`/`delta`/`done` 流式气泡。
2. **ChatService**：管 chat 消息持久化、session 摘要，**只有它发 done**。
3. **CoachGraphOrchestrator + LangGraph**：管 agent_run 观测，图走 **load_profile → route → plan → 并行 sub_agent → synthesize → guardrails**。

数据在 **PostgreSQL + pgvector**，知识和向量同库，方便 citation 审计。

---

## 【1:30–3:00】三个技术亮点

**第一，Multi-Agent 并行。** Planner 输出 JSON 任务列表后，用 LangGraph 的 **Send** 并行跑 training 和 nutrition 两个 sub_agent，每个 sub_agent 内部是 **ReAct + 工具调用**，状态通过 CoachState 的 **reducer** 自动 merge。

**第二，Hybrid RAG。** 不是纯向量，而是 **关键词 + 向量 RRF 融合**，对中文运动术语召回更稳；另外还有 **Graph RAG** 查实体关系，和向量互补。

**第三，工程化契约。** ChatService 和 Orchestrator **职责分离**——图里不写消息表；SSE 上单 agent 用 **replace** 一次出全文，多 agent 合并才 **delta** 流式。这套有专门文档和 49 个 pytest 覆盖。

---

## 【3:00–4:00】难点与解决

难点一是 **并行状态 merge 和 recovery**，用 LangGraph Send + serial_dispatch fallback 解决。

难点二是 **SSE 与 DB 一致性**，assistant 必须在 graph 跑完后由 ChatService 入库，再 `finalize_run`，最后才 `done`。

难点三是 **长上下文成本**，默认 **滑动窗口 + session 摘要**，benchmark 对比 full 模式 token 约省一半。

---

## 【4:00–4:45】成果

- **81** 条 benchmark 标注样本 + admin 仪表盘  
- **agent_run / steps / llm_calls** 全链路可观测  
- **三角色 RBAC**：用户、知识库编辑、admin  
- LoRA 实验脚本作为 portfolio 扩展，生产默认 API  

---

## 【4:45–5:00】收尾

如果展开，我可以 live 演示一条「增肌 + 膝伤」的多 Agent 请求，或深入讲 RAG 的 RRF 和 faithfulness 评测。  

---

## 备用一句

「这是一个 **LangGraph Multi-Agent + Hybrid RAG** 的垂直 Coach，核心不是套壳，而是 **Planning、并行、工具、评测、观测** 的完整闭环。」
