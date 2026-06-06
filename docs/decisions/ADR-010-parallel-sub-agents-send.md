# ADR-010: 并行 sub_agent 用 LangGraph Send

- **状态**: Accepted
- **关联**: [guide/04](../guide/04-Agent编排深度解析.md)

## 决策

多 PlanTask 时 `return [Send("sub_agent", payload), ...]`；CoachState reducer merge；关闭并行走 serial_dispatch。

## 面试一句话

「Send 是 LangGraph 原生并行，state reducer 自动 merge，比手写 gather 稳。」
