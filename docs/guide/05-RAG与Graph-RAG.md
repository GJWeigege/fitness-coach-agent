# 05 · RAG 与 Graph-RAG

| 元信息 | 内容 |
|--------|------|
| **预计阅读** | 18 分钟 |
| **前置知识** | [04-Agent编排深度解析](./04-Agent编排深度解析.md)、向量检索基础 |
| **相关 ADR** | [COACH_AGENT_REDESIGN](../specs/COACH_AGENT_REDESIGN.md) §3.8–§3.10 |

---

## 本节你将学到

- 知识库 ingest 分块与 embedding 流水线
- `RagService` 混合检索（向量 + 关键词 + RRF）算法细节
- 分数阈值 **0.35** 与 citation guard 的关系
- Graph-RAG：实体 linking 与 1-hop 上下文构建
- RAG 在 Agent 三条注入路径（prefetch / tool / guardrails）
- 面试常见「混合检索为什么」「Graph-RAG 价值」答法

---

## 1. RAG 在系统中的位置

```text
                    ┌─────────────────┐
  上传 Markdown/PDF │  IngestService   │
                    └────────┬────────┘
                             │ chunk 800 / overlap 120
                             ▼
                    ┌─────────────────┐
                    │ knowledge_chunks │ ← embedding 1024 (text-embedding-v3)
                    └────────┬────────┘
                             │
     用户提问 ────────────────┼──────────────────────────┐
                             ▼                          │
                    ┌─────────────────┐                 │
                    │   RagService    │                 │
                    │  hybrid retrieve│                 │
                    └────────┬────────┘                 │
              ┌──────────────┼──────────────┐           │
              ▼              ▼              ▼           │
      knowledge_prefetch  knowledge_search   graph enrich
              │              (tool)              │
              └──────────────┴──────────────────────┘
                             ▼
                    build_llm_messages / guardrails
                             ▼
                    assistant retrieved_chunks
```

**原则**：向量 RAG 是主通路；Graph 是 **补充结构化关联**，不替代检索。

---

## 2. 知识入库（Ingest）

**文件**：`backend/app/services/ingest_service.py`

| 步骤 | 实现 |
|------|------|
| 文本提取 | Markdown 直读；PDF 用 `pypdf` |
| 分块 | 字符窗 `INGEST_CHUNK_SIZE=800`，重叠 `INGEST_CHUNK_OVERLAP=120` |
| 哈希 | SHA256 `content_hash` 防重复 |
| 向量化 | `llm_client.embedding(chunks)` 批量 |
| 存储 | `KnowledgeDocument` + 多条 `KnowledgeChunk` |

触发方式：

- 启动 seed：`seed_demo_data.py` 加载 `backend/data/knowledge/*.md`（5 篇）
- API：`POST /knowledge/upload` → 202 BackgroundTasks
- Reindex：`POST /knowledge/documents/{id}/reindex`

---

## 3. RagService 混合检索

**文件**：`backend/app/services/rag_service.py`

### 3.1 关键词检索 `_keyword_search`

- 正则抽词：中文 ≥2 字 **或** 英文数字 ≥2 字符，最多 6 项
- SQL：`KnowledgeChunk.content ILIKE %term%`，`OR` 组合
- 分数：`1 / (60 + rank)`，标记 `source=keyword`

### 3.2 向量检索 `_vector_search`

- `embedding([query])` → pgvector `cosine_distance`
- 分数：`1 - distance`，标记 `source=vector`

### 3.3 RRF 融合 `_rrf_merge`

Reciprocal Rank Fusion，常数 **k=60**：

```text
RRF_score(chunk) = Σ 1/(k + rank_i)
最终 score = round(RRF * 10, 6)，source=hybrid
```

**为何 RRF**：向量与关键词分数量纲不同；RRF 只看排名，避免尺度校准问题。

配置：

- `RAG_HYBRID_ENABLED=true`（默认）
- `RAG_TOP_K=4`（融合后返回）
- `RAG_KEYWORD_TOP_K=8`（关键词候选池）

### 3.4 检索日志

每次 `retrieve` 写 `RetrievalLog`（query、top_k、results JSON），便于 observability 与 benchmark 对齐。

---

## 4. 分数阈值与 Citation Guard

**文件**：`backend/app/agent/guardrails.py`

`RAG_SCORE_THRESHOLD = **0.35**`（`config.py`）

`CoachGuardrails.citations_valid` 逻辑：

```text
1. 无 citation 或内容空 → invalid
2. top score ≤ 0 → invalid
3. top < rag_score_floor(0.01) → invalid
4. 若任一 citation source ∈ {hybrid, keyword} → valid（RRF 分标度低，~0.02–0.35）
5. 若 top ≥ 0.35（向量 cosine 语义）→ valid
6. 若 top 与 second 差距 ≥ rag_score_min_gap(0.004) → valid
7. 仅 1 条 substantive → valid
```

`apply_citation_guard`：当 intent ∈ {training, nutrition, safety, unknown} 且 **本轮调用了 knowledge_search** 但 citations 无效 → 替换为 `FALLBACK_NO_KNOWLEDGE`。

**面试点**：混合检索时必须对 hybrid/keyword **放宽阈值**，否则 RRF 分永远过不了 0.35。

---

## 5. Agent 侧三条 RAG 注入路径

### 路径 1：knowledge_prefetch（unknown 意图）

`nodes/knowledge_prefetch.py`：

- query = 用户原话
- 写 `rag_citations`、`graph_context`、`graph_entities_used`
- 下游 `coach_chitchat` 经 `build_llm_messages` 可见图谱块

### 路径 2：knowledge_search 工具

`tools/knowledge.py`：

- sub_agent ReAct 主动发起，可带定制 query / top_k
- `use_rag=false` → 返回「知识库检索已关闭」
- 结果进 tool message；guardrails 从 tool_calls **二次合并** citations

### 路径 3：apply_guardrails 合并

`collect_rag_citations(state.rag_citations, tool_calls)` 去重 chunk_id，写回 `retrieved_chunks` 供前端展示。

---

## 6. Graph-RAG 设计

**文件**：`backend/app/services/graph_service.py`、`graph_context.py`

### 6.1 数据模型

- `GraphEntity`：exercise / injury / nutrient 等，带 embedding
- `GraphEdge`：source --[relation_type]--> target
- `GraphEntityLink`：chunk ↔ entity 多对多 + confidence

Seed：`backend/app/db/seed_graph.py`（与 demo 知识库配套）。

### 6.2 检索后实体链接 `link_entities`

对 RAG 命中的每个 chunk：

1. 用 chunk 向量与 `GraphEntity.embedding` 余弦匹配
2. Top `ENTITY_MATCH_TOP_K=2`，confidence ≥ `LINK_CONFIDENCE_THRESHOLD=0.45`
3. 写入 `GraphEntityLink`

### 6.3 1-hop 上下文 `build_one_hop_context`

以 linked entity 为种子，查关联边，生成可读文本：

```text
图谱关联（1-hop）:
- 深蹲 --[targets]--> 股四头肌
- 深蹲 --[contraindicated_for]--> 膝关节损伤
```

注入 prompt：`【图谱补充】` 块（`format_graph_context_block`）。

### 6.4 graph_lookup 工具

`tools/graph_lookup.py`：按实体名 ILIKE 查询 + 1-hop，供 sub_agent **主动**查关系（与被动 enrich 互补）。

开关：`GRAPH_RAG_ENABLED=false` 时不注册 graph 工具、跳过 enrich。

---

## 7. 端到端示例

**用户**：「膝盖有旧伤，深蹲替代动作？」

```text
1. route_intent → safety 或 training
2. sub_agent 调用 knowledge_search("膝伤 深蹲 替代")
3. RagService hybrid → 命中《损伤预防与安全》chunk
4. enrich_from_rag → 链接 entity「深蹲」「膝关节损伤」
5. build_llm_messages 含 RAG 片段 + 1-hop 边
6. 可能再调 suggest_alternatives / check_contraindication
7. guardrails 校验 citation → append 免责声明
8. chat_messages.retrieved_chunks 存 citations
```

---

## 8. 配置速查

| 变量 | 默认 | 说明 |
|------|------|------|
| `USE_RAG_DEFAULT` | true | API 层默认 |
| `RAG_HYBRID_ENABLED` | true | 关闭则纯向量 |
| `RAG_SCORE_THRESHOLD` | 0.35 | 向量 citation 门槛 |
| `GRAPH_RAG_ENABLED` | true | 图谱增强 |
| `INGEST_CHUNK_SIZE` | 800 | 分块大小 |

---

## 9. 测试与 Benchmark

| 测试文件 | 覆盖 |
|----------|------|
| `test_rag.py` | RRF、keyword、vector |
| `test_guardrails.py` | 0.35 阈值、hybrid 豁免 |
| `test_graph.py` / `test_graph_context.py` | linking、1-hop |
| `test_ingest.py` | 分块入库 |
| `test_knowledge_api.py` | 上传/reindex API |

Benchmark faithfulness 可对照 `retrieved_chunks` 与标注 evidence。

---

## 代码锚点表

| 路径 | 职责 |
|------|------|
| `backend/app/services/rag_service.py` | 混合检索核心 |
| `backend/app/services/ingest_service.py` | 分块+embedding |
| `backend/app/services/graph_service.py` | Graph linking + 1-hop |
| `backend/app/agent/coach/graph_context.py` | prompt 格式化 |
| `backend/app/agent/tools/knowledge.py` | knowledge_search |
| `backend/app/agent/tools/graph_lookup.py` | graph_lookup |
| `backend/app/agent/guardrails.py` | citation guard |
| `backend/app/agent/coach/nodes/knowledge_prefetch.py` | unknown 预检索 |
| `backend/app/agent/coach/nodes/apply_guardrails.py` | citations 合并 |
| `backend/app/db/models.py` | KnowledgeChunk, Graph* |
| `backend/data/knowledge/*.md` | 种子语料 |
| `frontend/src/hooks/useKnowledge.ts` | 知识库管理 UI |
| `frontend/src/api/knowledge.ts` | 知识库 API |

---

## 常见追问

### Q1：为什么不用纯向量检索？

**答**：运动健康领域专有名词（动作名、补剂名）精确匹配重要；关键词 ILIKE + 向量语义 RRF 互补，benchmark 上召回更稳。

**追问链**：
- *追问*：关键词噪声怎么办？→ top_k 限制 + RRF 需两路都排名才靠前。

### Q2：RRF 常数 k=60 的含义？

**答**：排名 fusion 平滑项；k 越大，各 rank 贡献差距越小。60 是 IR 文献常用默认值，本项目未做网格搜索。

### Q3：Graph-RAG 和 Neo4j 方案比如何？

**答**：实体规模小，PostgreSQL 共库足够；无跨服务一致性成本；1-hop 已覆盖「动作-肌群-禁忌」面试演示。

**追问链**：
- *追问*：多 hop 呢？→ 当前刻意 1-hop 控 token；可扩展 BFS 深度配置。

### Q4：chunk 800 字符怎么定的？

**答**：平衡 embedding 语义完整性与检索粒度；overlap 120 防句子切断。可 A/B ingest 参数。

### Q5：用户关闭 RAG 还有什么价值？

**答**：profile/macros 等工具仍可用；回答偏通用模型知识，无 citation guard 强制 fallback。

### Q6：RetrievalLog 有什么用？

**答**：Debug 检索质量、Benchmark 复现、admin 分析 query→hit 分布。

### Q7：PDF 与 Markdown 处理差异？

**答**：同一 `_split_text`；PDF 经 pypdf 提取纯文本，可能丢排版。

### Q8：embedding 模型换维度怎么办？

**答**：需改 `EMBEDDING_DIM`、Alembic 迁移 vector 列、全量 reindex。

---

## 延伸阅读

- [LLM_ARCHITECTURE](../reference/LLM_ARCHITECTURE.md) — RAG 原理与 Chunk 策略
- [ARCHITECTURE](../reference/ARCHITECTURE.md) — RAG 流程图
- [04-Agent编排深度解析](./04-Agent编排深度解析.md) — prefetch 与 tool 调用
- [COACH_AGENT_REDESIGN](../specs/COACH_AGENT_REDESIGN.md) — Graph-RAG 验收项
