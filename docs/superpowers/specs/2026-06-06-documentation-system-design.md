# 文档体系设计规格

> **日期**: 2026-06-06  
> **状态**: Implemented  
> **目标**: 深度学习 + 面试应对 + onboarding

## 结构

```text
docs/
├── INDEX.md                 # 总导航
├── guide/                   # 12 章深度学习（中文）
├── reference/               # 契约/配置/验收
├── decisions/               # 12 ADR
├── interview/               # 口述稿 + FAQ 62 题
└── specs/                   # COACH_AGENT_REDESIGN 原始规格
```

## 实施阶段（已完成）

| 阶段 | 内容 |
|------|------|
| P0 | README、INDEX、CONFIG、目录迁移 |
| P1 | guide 03/04/05/11 |
| P2 | guide 06-10、decisions |
| P3 | guide 01/02/12、reference 迁移 |
| P4 | interview PITCH/FAQ/CHEATSHEET |
| P5 | 旧路径 redirect stub |

## 语言策略

- README：英文 Quick Start + 中文 Doc Map
- guide / interview / decisions：中文
- reference 契约：保留原有中英混排

## 验收

- [x] guide 12 章 + 代码锚点
- [x] ADR 12 条
- [x] FAQ 62 题（A–F）
- [x] 旧 docs 根路径 redirect
- [x] README 文档地图

## 维护

代码变更时同步更新：guide 代码锚点、CONFIG 表、FAQ 数字。
