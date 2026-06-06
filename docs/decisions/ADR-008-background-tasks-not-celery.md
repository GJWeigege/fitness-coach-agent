# ADR-008: MVP 用 BackgroundTasks，非 Celery

- **状态**: Accepted
- **关联**: [reference/COACH_HA](../reference/COACH_HA.md), [guide/03](../guide/03-系统架构与分层.md)

## 决策

ingest / reindex / benchmark 用 FastAPI BackgroundTasks；多实例部署需升级 Celery + Redis。

## 面试一句话

「单实例 MVP BackgroundTasks 够用，HA 文档写了 Celery 升级路径。」
