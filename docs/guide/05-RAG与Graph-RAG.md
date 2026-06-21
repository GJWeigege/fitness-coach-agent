# 05 · RAG 与 Graph-RAG

| 元信息 | 内容 |
|--------|------|
| **预计阅读** | 35 分钟 |
| **前置知识** | [04-Agent编排深度解析](./04-Agent编排深度解析.md)、向量检索基础 |
| **相关 ADR** | [COACH_AGENT_REDESIGN](../specs/COACH_AGENT_REDESIGN.md) §3.8–§3.10 |

---

## 本节你将学到

- 知识库 ingest：`##` 分块 + 标题前缀 + 导语处理
- `RagService` 混合检索 → 质量过滤 → Rerank → MMR 流水线
- `vector_score` / `rerank_score` 与 citation guard 的关系
- Graph-RAG：实体 linking 与 1-hop 上下文构建
- RAG 在 Agent 三条注入路径（prefetch / tool / guardrails）

---

## 1. RAG 在系统中的位置

```text
                    ┌─────────────────┐
  上传 Markdown/PDF │  IngestService   │
                    └────────┬────────┘
                             │ ## 分块 + 标题前缀（400/60 兜底）
                             ▼
                    ┌─────────────────┐
                    │ knowledge_chunks │ ← embedding 1024 (text-embedding-v3)
                    └────────┬────────┘
                             │
     用户提问 ────────────────┼──────────────────────────┐
                             ▼                          │
                    ┌─────────────────┐                 │
                    │   RagService    │                 │
                    │ hybrid retrieve │                 │
                    └────────┬────────┘                 │
              ┌──────────────┼──────────────┐           │
              ▼              ▼              │           │
      knowledge_prefetch  knowledge_search   │           │
         (+ graph)           (tool)         │           │
              │              │              │           │
              └──────────────┴──────────────┘           │
                    （Graph：prefetch 写 state；sub_agent 可另调 graph_lookup）
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
| 分块 | 有 `##` → 按小节切；每块前缀 `# 文档标题`；导语 ≥50 字单独成块，否则并入第一节 |
| 超长节 | 节内按段落/字符窗二次切（默认 `INGEST_CHUNK_SIZE=400`，`INGEST_CHUNK_OVERLAP=60`） |
| 无 `##` | 回退段落合并 + 字符窗（PDF/纯文本） |
| 哈希 | SHA256 `content_hash` 防重复 |
| 向量化 | `llm_client.embedding(chunks)` 批量 |
| 存储 | `KnowledgeDocument` + 多条 `KnowledgeChunk` |

触发方式：

- 启动 seed：`seed_demo_data.py` 加载 `backend/data/knowledge/*.md`
- API：`POST /knowledge/upload` → 202 BackgroundTasks
- Reindex：`POST /knowledge/documents/{id}/reindex`
- 全量 Reindex：`POST /knowledge/reindex-all` → 202，后台串行重建所有 `indexed`/`failed` 文档；跳过 `pending`/`reindexing` 及源文件缺失项；限流 `REINDEX_ALL_RATE`（默认 5 次/小时）
- 并发控制：进程内 `asyncio.Lock` 保证单 worker 下 bulk 互斥；**多 worker 部署时锁不跨进程**，需另行引入 DB/Redis 分布式锁

**重要**：修改分块策略或 `INGEST_CHUNK_*` 后必须 **全量 reindex**，否则旧 chunk 边界与 embedding 不一致。

---

## 3. RagService 检索流水线

**文件**：`backend/app/services/rag_service.py`

### 3.1 关键词检索 `_keyword_search`

- 长中文词拆 bigram（如「深蹲硬拉」→「深蹲」「硬拉」）
- SQL：`ILIKE` + term 命中数排序；`%` / `_` / `\` 转义防 wildcard 误匹配
- 标记 `source=keyword`，附带 `keyword_rank`

### 3.2 向量检索 `_vector_search`

- `embedding([query])` → pgvector `cosine_distance`
- 分数：`vector_score = 1 - distance`，候选池 `RAG_VECTOR_CANDIDATE_K=20`

### 3.3 RRF 融合 `_rrf_merge`

Reciprocal Rank Fusion，常数 **k=60**：

```text
RRF_score(chunk) = Σ 1/(k + rank + 1)   # rank 为 0-based 排名
最终 score = round(RRF * 10, 6)，source=hybrid
```

保留 `vector_score`、`keyword_hit`、`keyword_rank`、`vector_rank` 供下游过滤与 guard 使用。

### 3.4 质量过滤 `_filter_results`

保留条件（满足任一）：

```text
1. vector_score ≥ RAG_VECTOR_SCORE_MIN (0.55)
2. keyword_hit 且 vector_score ≥ RAG_VECTOR_SCORE_MIN_WITH_KEYWORD (0.45)
3. 同时在 keyword Top3 与 vector Top10
4. keyword Top3 精确命中（vector_score 可为 0）
```

### 3.5 Cross-encoder Rerank

- 模型：`gte-rerank-v2`（DashScope 原生 rerank 端点，非 compatible-mode）
- 对过滤后 Top `RAG_RERANK_CANDIDATE_K=15` 重排
- 写入 `rerank_score`；API 失败 / 空响应 → 回退 hybrid 排序
- 部分 rerank 响应 → 记录 warning，未排序项按原顺序追加

### 3.6 MMR 多样性 `_mmr_select`

- 用库内 chunk embedding 做 MMR（`RAG_MMR_LAMBDA=0.7`）
- 从 rerank 候选中选出差异更大的 Top `RAG_TOP_K=3`
- 之后 `_apply_per_document_limit`：每文档最多 2 块、相邻 index 去重

**注意**：MMR + 同文档限流后，最终条数可能 **少于** `RAG_TOP_K`（多样性优先，不回填）。

### 3.7 MMR 公式与贪心实现

MMR（Maximal Marginal Relevance）在 **rerank 后的候选池** 中迭代选 chunk，平衡相关性与多样性：

```text
MMR(d) = λ · Relevance(d) - (1-λ) · max_{s∈Selected} cos_sim(embed(d), embed(s))
```

- `Relevance(d)`：优先 `rerank_score`，否则 `vector_score`，否则 hybrid `score`
- `λ = RAG_MMR_LAMBDA`（默认 0.7）越大越偏相关性
- `cos_sim`：chunk embedding 间余弦相似度（`_cosine_similarity` 纯 Python，不二次调 API）

实现为 **贪心**：每轮从 `remaining` 取 MMR 最高者加入 `selected`，直到 `len(selected)==top_k` 或 `remaining` 空。首条无已选集时 `mmr_score = relevance`。

### 3.8 retrieve() 端到端伪代码

```python
async def retrieve(db, query, top_k):
    if rag_hybrid_enabled:
        kw = keyword_search(query, RAG_KEYWORD_TOP_K)      # ILIKE + term 计数
        vec = vector_search(query, RAG_VECTOR_CANDIDATE_K)   # pgvector cosine
        merged = rrf_merge(kw, vec, k=60)                  # 双路排名融合
        filtered = quality_filter(merged, kw_top3, vec_top10)
        results = finalize(filtered, top_k)                  # rerank → mmr → doc limit
    else:
        vec = vector_search(...)
        filtered = [x for x in vec if x.vector_score >= RAG_VECTOR_SCORE_MIN]
        results = finalize(filtered, top_k)
    write RetrievalLog(...)
    return results
```

`finalize` = `_apply_rerank`（gte-rerank-v2，失败回退 hybrid 序）→ `_mmr_select`（可选）→ `_apply_per_document_limit`（每 doc ≤2 块、相邻 index 去重）。

### 3.9 检索日志

每次 `retrieve` 写 `RetrievalLog`（query、top_k、results JSON，含 hybrid/rerank/mmr 标记）。

---

## 4. 分数阈值与 Citation Guard

**文件**：`backend/app/agent/guardrails.py`

前端展示分数优先级：`rerank_score` → `vector_score` → `score`（RRF）。

`CoachGuardrails.citations_valid` 逻辑：

```text
hybrid / keyword 来源：
  1. max(rerank_score) > 0 → valid
  2. max(vector_score) ≥ 0.45 → valid
  3. 任一 citation keyword_rank < RAG_KEYWORD_TOP_FOR_FILTER(3) → valid
  4. 否则 invalid

纯 vector 来源：
  1. top score ≤ 0 或 < rag_score_floor → invalid
  2. top ≥ RAG_SCORE_THRESHOLD(0.35) → valid
  3. top 与 second 差距 ≥ rag_score_min_gap → valid
  4. 仅 1 条 substantive → valid
```

`apply_citation_guard`：当 intent ∈ {training, nutrition, safety, unknown} 且 **本轮调用了 knowledge_search** 但 citations 无效 → 替换为 `FALLBACK_NO_KNOWLEDGE`。

---

## 5. Agent 侧三条 RAG 注入路径

### 路径 1：knowledge_prefetch（unknown 意图）

`nodes/knowledge_prefetch.py`：

- query = 用户原话
- 写 `rag_citations`、`graph_context`、`graph_entities_used`

### 路径 2：knowledge_search 工具

`tools/knowledge.py`：

- sub_agent ReAct 主动发起，可带定制 query / top_k
- 结果进 tool message；guardrails 从 tool_calls **二次合并** citations

### 路径 3：apply_guardrails 合并

`collect_rag_citations(state.rag_citations, tool_calls)` 去重 chunk_id，写回 `retrieved_chunks` 供前端展示。

---

## 6. Graph-RAG 设计（深入）

**文件**：`backend/app/services/graph_service.py`、`graph_context.py`、`db/seed_graph.py`

Graph-RAG **不替代**向量检索，而是在 RAG 命中 chunk 后，把结构化实体关系 **注入 system prompt**，帮助 LLM 理解「动作—禁忌—营养」关联。

### 6.1 数据模型

| 表 | 含义 | 示例 |
|----|------|------|
| `graph_entities` | 实体节点 + embedding | `exercise:深蹲`、`injury:膝关节损伤` |
| `graph_edges` | 有向关系 | `深蹲 --[contraindicated_for]--> 膝关节损伤` |
| `graph_entity_links` | chunk ↔ entity 动态链接 | RAG 检索时写入，带 `confidence` |

Seed 数据在 `seed_graph.py` 预置常见健身实体；**运行时**通过 embedding 相似度把 chunk 链接到 entity，无需 NLP 实体抽取 pipeline。

### 6.2 实体链接算法（link_entities）

对每条 RAG 命中 chunk：

1. 取 chunk 的 **已有 embedding**（与向量检索同一向量，无额外 API）
2. 在 `graph_entities` 上做 pgvector 最近邻，Top `ENTITY_MATCH_TOP_K=2`
3. 保留 `confidence = 1 - cosine_distance ≥ 0.45` 的匹配
4. 写入 `GraphEntityLink(chunk_id, entity_id, confidence)`（幂等：已存在则跳过）

返回去重后的 `entity_ids` 与 `entity_names`，供 observability 与 `graph_entities_used` 字段。

### 6.3 1-hop 上下文（build_one_hop_context）

以链接到的 entity 为种子，查询 `graph_edges` 中任一端点在种子集合的边，格式化为可读行：

```text
图谱关联（1-hop）:
- 深蹲 --[contraindicated_for]--> 膝关节损伤
- 腿举 --[alternative_for]--> 深蹲
```

若无边，仅列出种子实体名称。结果经 `format_graph_context_block` 包在 `【图谱补充】` 下，append 到 `build_llm_messages` 的 system `context_block`。

### 6.4 三条触发路径对比

| 路径 | 触发 | graph_context 写入时机 | graph_lookup 工具 |
|------|------|------------------------|-------------------|
| knowledge_prefetch | intent=unknown | prefetch 节点内 `resolve_graph_context_for_rag` | 不自动调用 |
| knowledge_search 工具 | sub_agent ReAct | **不自动** enrich；结果仅进 tool message，citations 在 guardrails 合并 | 需 LLM 另调 `graph_lookup` 才得 1-hop |
| graph_lookup 工具 | sub_agent 主动 | 工具返回 `context` 进 tool message（不写 state.graph_context） | 按实体名 ILIKE 查库 + 1-hop |

`GRAPH_RAG_ENABLED=false` 时：`resolve_graph_context_for_rag` 短路返回 `(None, [])`，`GraphLookupTool` 不注册。

### 6.5 失败与降级

`resolve_graph_context_for_rag` 捕获全部异常并 log，**主链路继续**——与 RAG rerank 失败回退同理。Benchmark 中 `must_cite` 不依赖 graph；graph 仅增强回答质量。

### 6.6 与 Neo4j 方案的取舍

PostgreSQL 三表 + pgvector 足够 MVP：**同一 DB 事务**内完成 RAG + link + 1-hop，运维与 backup 简单。Neo4j 适合超大规模图谱与复杂图算法；本项目 1-hop 只读查询，SQL 足够。

---

## 7. 端到端示例

**用户**：「膝盖有旧伤，深蹲替代动作？」

```text
1. route_intent → safety 或 training
2. sub_agent 调用 knowledge_search("膝伤 深蹲 替代")
3. RagService: hybrid → filter → rerank → MMR → 返回 1~3 条 citation
4. （可选）sub_agent 再调 graph_lookup("深蹲") 获取 1-hop；unknown 路径则 prefetch 已写 graph_context
5. guardrails 校验 citation（rerank/vector/keyword_rank）
6. chat_messages.retrieved_chunks 存 citations（前端展示分数与来源标签）
```

---

## 8. 配置速查

| 变量 | 默认 | 说明 |
|------|------|------|
| `USE_RAG_DEFAULT` | true | API 层默认 |
| `RAG_HYBRID_ENABLED` | true | 关闭则纯向量 |
| `RAG_TOP_K` | 3 | 最终返回条数上限 |
| `RAG_KEYWORD_TOP_K` | 12 | 关键词候选池 |
| `RAG_VECTOR_CANDIDATE_K` | 20 | 向量候选池 |
| `RAG_VECTOR_SCORE_MIN` | 0.55 | 质量过滤 / 纯向量门槛 |
| `RAG_VECTOR_SCORE_MIN_WITH_KEYWORD` | 0.45 | 关键词+向量联合门槛 |
| `RAG_RERANK_ENABLED` | true | Cross-encoder rerank |
| `RAG_RERANK_CANDIDATE_K` | 15 | 送入 rerank 的候选数 |
| `RAG_MMR_ENABLED` | true | MMR 多样性 |
| `RAG_MMR_LAMBDA` | 0.7 | MMR 相关性权重（越大越偏相关性） |
| `RAG_MAX_CHUNKS_PER_DOCUMENT` | 2 | 同文档 chunk 上限 |
| `COACH_RERANK_MODEL` | gte-rerank-v2 | Rerank 模型 |
| `INGEST_CHUNK_SIZE` | 400 | 节内二次切分上限 |
| `INGEST_CHUNK_OVERLAP` | 60 | 字符窗重叠 |
| `GRAPH_RAG_ENABLED` | true | 图谱增强 |

---

## 9. 测试与 Benchmark

| 测试文件 | 覆盖 |
|----------|------|
| `test_rag.py` | RRF、filter、rerank 回退/部分响应、MMR、ILIKE 转义、向量阈值 |
| `test_guardrails.py` | hybrid rerank/vector/keyword_rank 校验 |
| `test_ingest.py` | `##` 分块、标题前缀、导语规则 |
| `test_graph.py` / `test_graph_context.py` | linking、1-hop |
| `test_knowledge_api.py` | upload / reindex / reindex-all、限流、409、skip 规则 |

---

## 代码锚点表

| 路径 | 职责 |
|------|------|
| `backend/app/services/rag_service.py` | 混合检索 + rerank + MMR |
| `backend/app/services/ingest_service.py` | Markdown 分块 + embedding |
| `backend/app/llm/dashscope_client.py` | embedding + rerank API |
| `backend/app/agent/guardrails.py` | citation guard |
| `frontend/src/components/chat/MessageBubble.tsx` | citation 分数/来源/截断展示 |

---

## 常见追问

### Q1：为什么不用纯向量检索？

**答**：专有名词精确匹配重要；关键词 ILIKE + 向量语义 RRF 互补；rerank 进一步提升 Top 精度。

### Q2：RRF 分为什么和 vector_score 差很多？

**答**：RRF 只看排名，标度约 0.02–0.18；展示与 guard 用 `rerank_score` / `vector_score`，不用 RRF 分。

### Q3：chunk 怎么切的？

**答**：Markdown 优先按 `##` 小节，每块带 `# 标题` 前缀；超长节再 400 字切。改策略后需 reindex。

### Q4：Rerank 和 MMR 分别解决什么？

**答**：Rerank 用 cross-encoder 精排 query–passage 相关性；MMR 在精排结果里选语义差异更大的块，减少重复段落。

### Q5：为什么有时返回少于 3 条？

**答**：质量过滤、同文档限流、相邻 chunk 去重会主动丢弃弱相关/重复块；属预期行为。

### Q6：RetrievalLog 有什么用？

**答**：Debug 检索质量、Benchmark 复现、分析 query→hit 分布。

---

## 延伸阅读

- [LLM_ARCHITECTURE](../reference/LLM_ARCHITECTURE.md) — RAG 原理与 Chunk 策略
- [ARCHITECTURE](../reference/ARCHITECTURE.md) — RAG 流程图
- [04-Agent编排深度解析](./04-Agent编排深度解析.md) — prefetch 与 tool 调用
- [COACH_AGENT_REDESIGN](../specs/COACH_AGENT_REDESIGN.md) — Graph-RAG 验收项
