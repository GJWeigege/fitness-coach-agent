# ADR-005: Graph RAG 存 PostgreSQL，不引入 Neo4j

- **状态**: Accepted
- **关联**: [guide/05](../guide/05-RAG与Graph-RAG.md)

## 背景

动作-肌群-禁忌有关系，向量 alone 不够。

## 决策

`graph_entities` / `graph_relations` 表 + `graph_lookup` 工具；`GRAPH_RAG_ENABLED` 可关。

## 面试一句话

「实体几百条 MVP 用 PG 表够了，Graph 补充 RAG，不上 Neo4j 集群。」
