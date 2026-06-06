# ADR-011: CoT 默认入库、不 SSE 推送

- **状态**: Accepted
- **关联**: [guide/04](../guide/04-Agent编排深度解析.md)

## 决策

`COT_ENABLED=true`，`COT_SSE_ENABLED=false`；CoT 进 cot_traces / agent_steps，默认不对用户流式 reasoning。

## 面试一句话

「CoT 给观测和排障，默认不推给用户，省带宽也防泄露链式推理。」
