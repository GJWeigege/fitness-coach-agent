# ADR-002: ChatService 与 CoachGraphOrchestrator 职责分离

- **状态**: Accepted
- **关联**: [guide/03](../guide/03-系统架构与分层.md), specs §2, §3.5

## 背景

聊天需要同时：持久化消息、跑 Agent、SSE 推送、更新 session 摘要。

## 考虑的选项

| 选项 | 优点 | 缺点 |
|------|------|------|
| 全在 Orchestrator | 单入口 | 图内写 DB 破坏 LangGraph 纯函数性 |
| 全在 ChatService | 简单 | Agent 逻辑膨胀 |
| **分离** | 边界清晰 | 两个类协作 |

## 决策

- **ChatService**：chat_messages、turn_count、maybe_update_summary、**done/error**
- **Orchestrator**：agent_run/steps/llm_calls、LangGraph、**run/step/delta/replace**、CoachRunResult

图内 **不** 写 chat_messages。

## 后果

- done 语义 = assistant 已入库 + finalize_run 完成
- 测试可分别 mock 两层（test_chat_stream, test_coach_graph）

## 面试一句话

「ChatService 管聊天持久化和 done，Orchestrator 管 Agent 执行和中间 SSE，LangGraph 里不写消息表。」
