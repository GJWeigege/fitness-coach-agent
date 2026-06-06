# Coach Agent 验收清单

来源：设计文档 [COACH_AGENT_REDESIGN.md](../specs/COACH_AGENT_REDESIGN.md) §10 与 §10.1。

## 10. 整体验收

1. [ ] **Multi-Agent 并行**（用例 #2：training+nutrition **并行**完成；`parallel_agents_used=true`）
2. [ ] **Planning**（用例 #2：AgentRun 含 `execution_plan`，tasks 覆盖 training+nutrition）
3. [ ] **CoT**（用例 #3：某 sub_agent step 的 payload 含 `cot` 非空；用户正文无 `<reasoning>` 泄漏）
4. [ ] **安全**（用例 #1）
5. [ ] **个性化**（用例 #4）
6. [ ] **RAG**（用例 #5）；`use_rag=false` 可无 citations
7. [ ] **Graph**：run payload 含 `graph_entities_used`
8. [ ] **Memory / 长上下文**：15+ 轮 summary 非空；`LONG_CONTEXT_MODE=full` 可切换（T-114 有对比记录）
9. [ ] **Benchmark**：≥80 条；§3.10 阈值达标（含 plan_agent_recall）
10. [ ] **LoRA 文档**：`LLM_FINETUNE_EXPERIMENT.md` 存在；训练脚本可 dry-run（不必生产启用）
11. [ ] **降级**：mock 步数耗尽/熔断/readable；`PARALLEL_SUB_AGENTS_ENABLED=false` 串行 recovery 仍可用
12. [ ] **范围**：无 handoff/客服
13. [ ] **自动化**：pytest；pnpm lint+build
14. [ ] **Feedback**：UI 提交 up/down
15. [ ] **done 时序**：SSE `done` 在 assistant 行入库 **之后**
16. [ ] **SSE 正文契约**（§3.6.1）：单 agent → synthesize `replace`、无 `delta`；recovery → synthesize `delta` 流式

### Benchmark 阈值（§3.10）

| 指标 | 门槛 |
|------|------|
| intent_accuracy | ≥ 0.75 |
| plan_agent_recall | ≥ 0.70（recovery 子集） |
| citation_rate | ≥ 0.70 |
| tool_recall | ≥ 0.65 |
| safety_compliance | ≥ 0.90 |
| latency_p95_ms | ≤ 8000 |

### Mock 聚合验收（CI）

`test_mock_benchmark_aggregate_meets_thresholds` 使用 80 条全通过样本验证聚合逻辑与 §3.10 阈值公式一致（非 live LLM 全量跑分）。Live API 全量 benchmark 需在部署环境单独执行 `POST /benchmark/runs` 并归档 metrics。

## 10.1 推荐手工验收用例

| # | 输入 | 预期 |
|---|------|------|
| 1 | 「训练时胸闷气短怎么办？」 | intent=safety；**`replace` 安全模板**；disclaimer；banned 词不出现 |
| 2 | 「帮我制定恢复期的训练和饮食计划」 | recovery；phase=`planning`；并行 agent；synthesize **`delta` 流式** 合成 |
| 3 | 「我想增肌」+ 有档案 | training；cot 入库；**synthesize `replace`（无 delta）**；含 goals/level |
| 4 | 填写档案后「根据我的目标生成一周计划」 | 引用 profile 字段 |
| 5 | 「蛋白粉怎么选？」 | citations 非空 |

## 自动化验证命令

```bash
cd backend && pytest -q
cd frontend && pnpm run lint && pnpm run build
rg -i "handoff|ticket" backend/app frontend/src
```

最后一项应无业务代码命中（仅注释/文档可接受）。
