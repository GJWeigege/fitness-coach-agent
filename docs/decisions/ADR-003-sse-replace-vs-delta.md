# ADR-003: synthesize 透传用 replace、多 agent 合并用 delta

- **状态**: Accepted
- **关联**: [guide/04](../guide/04-Agent编排深度解析.md), [guide/08](../guide/08-前端与SSE.md), [reference/AGENT_SSE](../reference/AGENT_SSE.md)

## 背景

前端需要流式体验，但不同 synthesize 路径产出形态不同。

## 决策

| 路径 | SSE |
|------|-----|
| 单 agent / chitchat / 安全模板 | **1 次 replace**（完整正文） |
| 多 agent LLM 合并 | **delta** 流式 |
| guardrails 改写 | 可选再 **1 次 replace** |

sub_agent **不**向客户端推正文。

## 面试一句话

「单 agent 答案已经完整，一次 replace；只有多 agent 要 LLM 合并时才 delta 流式。」
