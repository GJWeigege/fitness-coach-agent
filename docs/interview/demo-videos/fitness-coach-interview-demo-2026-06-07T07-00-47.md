# Fitness Coach 面试演示录屏

- 录制时间：2026/6/7 15:02:36
- 视频文件：`fitness-coach-interview-demo-2026-06-07T07-00-47.webm`
- 前端：http://localhost:5173
- 演示账号：coach_demo / admin_demo，密码 `Demo@123456`

## 演示步骤
- 1. 登录 coach_demo
- 2. coach_demo 健身档案：目标、膝伤限制与训练记录
- 3. Chat：新建会话并发送典型面试问题（增肌 + 膝伤）
- 4. 展开 Agent 执行过程与知识引用
- 5. 切换 admin_demo，展示管理端能力
- 6. admin_demo 知识库：RAG 文档列表与索引管理
- 7. admin_demo Benchmark：评测指标与历史运行详情
- 8. admin_demo Agent Runs：全链路观测 timeline
- 9. 结束

## 推荐话术（5 分钟）

1. **Profile**：用户档案（目标/伤病/器械）驱动个性化 tool 与建议。
2. **Chat**：LangGraph Multi-Agent 并行 training/nutrition，Agent Steps 可观测。
3. **RAG**：回复底部 citation 来自 Hybrid RAG，不是模型内化。
4. **Knowledge**：kb 文档 ingest + pgvector 索引，支持重建。
5. **Benchmark**：81 条样本 faithfulness / intent / citation 等指标。
6. **Agent Runs**：agent_run / llm_calls 全链路 timeline。

## 重新录制

```bash
cd scripts/demo
npm install && npm run install-browser
npm run record
```

更多口述稿见 [PITCH-15min.md](../PITCH-15min.md)。
