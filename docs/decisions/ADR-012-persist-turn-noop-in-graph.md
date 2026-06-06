# ADR-012: persist_turn 为图内 no-op 节点

- **状态**: Accepted
- **关联**: [guide/03](../guide/03-系统架构与分层.md), ADR-002

## 决策

保留 `persist_turn` 节点但空实现，文档化「图不持久化 turn」；实际写库在 ChatService。

## 面试一句话

「persist_turn 占位，强调持久化在图外，避免以后有人在图里写消息表。」
