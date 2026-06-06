# ADR-004: 默认启用 Hybrid RAG（向量 + 关键词 RRF）

- **状态**: Accepted
- **关联**: [guide/05](../guide/05-RAG与Graph-RAG.md)

## 背景

中文运动术语存在 rare token；纯向量可能语义漂移或漏召回。

## 决策

`RAG_HYBRID_ENABLED=true`：keyword ILIKE + pgvector cosine → RRF(k=60) → threshold 0.35。

## 面试一句话

「中文垂直领域用 Hybrid RRF，关键词补向量盲区。」
