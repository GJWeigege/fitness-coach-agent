# Coach Agent SSE 协议

> 与 [COACH_AGENT_REDESIGN.md](../specs/COACH_AGENT_REDESIGN.md) §3.6 / §3.6.1 一致。`done` **仅由 ChatService** 发出；`result` **仅 ChatService 内部消费**。

## 事件类型

| type | 发出方 | 说明 |
|------|--------|------|
| `run` | Orchestrator | 回合开始，`run_id` + `trace_id` |
| `step` | Orchestrator / ChatService | 思考步骤；`memory_summary` 由 ChatService 步骤 4 发出 |
| `tool_call` / `tool_result` | Orchestrator | 工具调用（`AGENT_ENABLE_THINKING_STEPS` 时） |
| `delta` | Orchestrator | **仅 synthesize 多 agent LLM 合并**；`content` 为增量片段 |
| `replace` | Orchestrator | synthesize 透传或 apply_guardrails 改写；`content` 为整段正文 |
| `session` | Orchestrator | `session_id` + `citations` |
| `result` | Orchestrator | 内部 `CoachRunResult`，**不转发客户端** |
| `done` | **ChatService** | 全流程结束（assistant 已入库且 `finalize_run` 完成） |
| `error` | 任一方 | 含 `message`、可选 `trace_id` |

## §3.6.1 正文流式契约

```text
收到 run → 初始化空 assistant 气泡
收到 delta → append content（仅 recovery 等合并路径会出现）
收到 replace → 用 content 整段替换当前气泡（覆盖此前 delta）
收到 done → 锁定；内容以 DB / result 为准做最终校验可选
```

### replace / delta 规则

| synthesize 路径 | 对用户 SSE | 说明 |
|-----------------|------------|------|
| 透传（单 agent / chitchat / unknown / `safety_blocked`） | **仅 1 次 `replace`** | `content` = 完整 `final_answer`；**不发 `delta`** |
| 多 agent LLM 合并（recovery 等） | **`delta` 流式** | synthesize 内 `chat_stream` 逐 chunk yield `delta`；结束后写入 `state.final_answer` |

**`apply_guardrails` 之后**：若改写正文 → 再 yield **1 次 `replace`**（整段覆盖）；若未改写 → 透传路径已在 synthesize 发过 replace，合并路径以累积 delta 为准。

### 典型正文序列

| 场景 | 典型 SSE 正文序列 |
|------|-------------------|
| 单 agent（用例 #3） | `replace`（synthesize）→ 可选 `replace`（guardrails）→ `done` |
| recovery 合并（用例 #2） | `delta`×N（synthesize）→ 可选 `replace`（guardrails）→ `done` |
| 安全拦截（用例 #1） | `replace`（synthesize 安全模板）→ `done` |

sub_agent / coach_chitchat **不向客户端推送正文**（无 `delta`/`replace`）。

## step 过滤（`on_chain_start`）

| 节点 | SSE |
|------|-----|
| `route_intent` | phase=`routing` |
| `plan_execute` | phase=`planning` |
| `sub_agent(*)` | phase=`{agent}_agent`，detail.agent=`training`\|`nutrition`\|`safety`\|`profile` |
| `safety_review` | phase=`safety_review` |
| `synthesize` | phase=`synthesizing` |
| `load_profile`, `dispatch_sub_agents`, `apply_guardrails`, `persist_turn`, `knowledge_prefetch` | **不发 step** |

## ChatService 七步契约（§3.5）

1. persist user + `increment_turn_count` + commit  
2. `stream_turn` → 转发 SSE（不含 `done`）；吞掉 `type=result`  
3. `maybe_update_summary`（older 对；**早于** assistant 入库）  
4. persist assistant（来自 `CoachRunResult.final_answer`）+ commit  
5. 可选 yield `step` phase=`memory_summary`  
6. `finalize_run(...)`  
7. yield `done`

`/chat/send`：聚合正文 — 有 `replace` 取最后一次 `replace.content`，否则拼接全部 `delta`；入库仍以 `type=result` 为准。
