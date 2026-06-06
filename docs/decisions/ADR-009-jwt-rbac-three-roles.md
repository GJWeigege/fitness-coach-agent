# ADR-009: JWT + 三角色 RBAC

- **状态**: Accepted
- **关联**: [guide/10](../guide/10-安全护栏与RBAC.md)

## 决策

user / kb_editor / admin 三角色 + permission 字符串；API `require_permissions` + 前端 Sidebar 门控。

## 面试一句话

「三角色覆盖用户聊天、编辑知识库、admin 看 run 和跑 benchmark。」
