# ADR-001: LangGraph 编排但不用 LangChain ChatModel 适配层

- **状态**: Accepted
- **日期**: 2026-06-05
- **关联**: [guide/02](../guide/02-技术栈全解.md), [guide/04](../guide/04-Agent编排深度解析.md), specs §3.3

## 背景

LangGraph 节点需要调用 DashScope LLM 与自研工具。LangChain 提供 `BaseChatModel` 适配多种模型。

## 考虑的选项

| 选项 | 优点 | 缺点 |
|------|------|------|
| LangChain ChatModel + LangGraph | 生态统一 | 多一层抽象；prompt 难追踪；mock 链长 |
| **直接 DashScopeClient** | 调用链清晰；单测 mock 一层 | 自写 tool streaming 协议 |
| 纯 asyncio 状态机 | 无 LangGraph 依赖 | 并行 Send、reducer 需自实现 |

## 决策

采用 **LangGraph + DashScopeClient**；`requirements.txt` 仅显式依赖 `langgraph`（传递使用 `langchain-core` 的 RunnableConfig/Send）。

## 后果

- **正面**：49 个测试 mock `DashScopeClient`；节点代码可读。
- **负面**：换 LLM 需改 client，非配置即用。
- **缓解**：DashScope 兼容 OpenAI API；client 接口稳定。

## 面试一句话

「LangGraph 管编排，LLM 调我们自己的 DashScopeClient，不套 LangChain ChatModel，方便测试和排障。」
