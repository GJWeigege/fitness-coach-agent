# 面试一页纸速查

## 数字

| 项 | 值 |
|----|-----|
| Coach 工具数 | **7** |
| Benchmark 样本 | **81** 条（`coach_eval.jsonl`，验收 ≥80） |
| Embedding 维度 | **1024** |
| Chunk size / overlap | **400 / 60**（节内二次切分；Markdown 优先 `##` 小节） |
| RAG Top-K / threshold | **3 / 0.35** |
| Memory 窗口 / token 顶 | **8 turns / 12000** |
| sub_agent 最大 tool 步 | **4** |
| 每轮最大 sub_agent | **2** |
| 测试文件 | **49** |
| RBAC 角色 | **3**（user, kb_editor, admin） |
| Demo 密码 | **Demo@123456** |
| 预录演示视频 | [demo-videos/](demo-videos/)（Profile→Chat→Knowledge→Benchmark→Agent Runs） |

## 关键路径

| 概念 | 文件 |
|------|------|
| 聊天七步 | `services/chat_service.py` |
| LangGraph 图 | `agent/coach/graph.py` |
| 并行 Send | `nodes/dispatch_sub_agents.py` |
| Hybrid RAG | `services/rag_service.py` |
| SSE 前端 | `hooks/useSessions.ts` |
| 权限 | `auth/permissions.py` |

## 架构一句

User → React SSE → ChatService（消息+done）→ Orchestrator → LangGraph → Tools/RAG → PG+pgvector

## SSE 一句

单 agent **replace**；多 agent 合并 **delta**；**done 仅 ChatService**

## ADR 速记

- 001 不用 LC ChatModel  
- 002 Chat/Orchestrator 分离  
- 003 replace vs delta  
- 004 Hybrid RAG  
- 010 Send 并行  

## 文档入口

[INDEX.md](../INDEX.md) · [FAQ.md](FAQ.md) · [PITCH-5min.md](PITCH-5min.md)
