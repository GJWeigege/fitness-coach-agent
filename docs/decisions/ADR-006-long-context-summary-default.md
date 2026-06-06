# ADR-006: 默认 LONG_CONTEXT_MODE=summary

- **状态**: Accepted
- **关联**: [guide/06](../guide/06-记忆与长上下文.md), [reference/LLM_ARCHITECTURE](../reference/LLM_ARCHITECTURE.md)

## 决策

默认 `summary`（窗口 + session.summary）；`full` 用 qwen-long，faithfulness 略高但 token/latency ~2×。

## 面试一句话

「默认滑动窗口加摘要，成本和延迟可控；极长会话再开 full。」
