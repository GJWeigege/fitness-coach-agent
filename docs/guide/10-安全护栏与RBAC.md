# 10 — 安全护栏与 RBAC

> **阅读时间**：约 45 分钟  
> **前置章节**：[03-系统架构与分层](03-系统架构与分层.md)、[09-评测与观测](09-评测与观测.md)  
> **相关 ADR**：[ADR-009](../decisions/ADR-009-jwt-rbac-three-roles.md)

---

## 本节你将学到

- `CoachGuardrails` 五层防护：诊断禁语、Citation Guard、免责声明、CoT 脱敏、SSE replace
- `safety_review_node` 与 guardrails 的分工（红旗拦截 vs 输出后处理）
- 自研 JWT（HMAC-SHA256）签发/校验与 `require_permissions` 依赖注入
- 三角色 `user` / `kb_editor` / `admin` 权限矩阵与前后端对齐方式
- 登录防暴力、限流、CORS 等配套安全控制

---

## 1. 安全体系总览

```text
请求进入
  ├─ JWT 认证 (get_current_user)
  ├─ RBAC 鉴权 (require_permissions / 会话级检查)
  ├─ Rate limit / Login lockout
  └─ Chat 业务
        ├─ safety_review_node（回合中拦截红旗症状）
        ├─ apply_guardrails_node（输出后处理）
        └─ 入库 + SSE replace（若改写）
```

**纵深防御**：LLM 可能幻觉 → 图谱/工具约束 + 输出护栏 + 免责声明；权限最小化 → 细粒度 permission 字符串。

---

## 2. CoachGuardrails 详解

**文件**：`backend/app/agent/guardrails.py`  
**节点入口**：`backend/app/agent/coach/nodes/apply_guardrails.py`

### 2.1 常量与禁语表

| 常量 | 用途 |
|------|------|
| `COACH_DISCLAIMER` | 固定医疗免责声明 appended |
| `FALLBACK_NO_KNOWLEDGE` | Citation Guard 失败时的统一回复 |
| `CITATION_GUARD_INTENTS` | training/nutrition/safety/unknown 受引用约束 |
| `banned_diagnosis.txt` | 禁止诊断用语列表（如具体病名诊断） |

`load_banned_diagnosis_terms()` 启动时加载；文件缺失则列表为空，不阻塞启动。

### 2.2 apply_guardrails 流水线

```140:168:backend/app/agent/guardrails.py
    def apply_guardrails(self, content, *, intent, citations, knowledge_searched, append_disclaimer=True):
        text = content
        if self.contains_banned_diagnosis(text):
            text = self.strip_banned_diagnosis(text)      # ① 诊断禁语 → 【已省略】
        text = self.apply_citation_guard(...)               # ② 引用有效性
        if append_disclaimer and text != FALLBACK_NO_KNOWLEDGE:
            if intent in CITATION_GUARD_INTENTS | {"recovery", "profile"}:
                text = self.ensure_disclaimer(text)       # ③ 免责声明
                text = self.dedupe_disclaimer(text)
        return text, text != original
```

**节点侧 SSE**：若 `modified` 且配置了 `emit`，yield `replace` 事件覆盖前端正文。

```17:26:backend/app/agent/coach/nodes/apply_guardrails.py
    content, modified = guardrails.apply_guardrails(...)
    if modified and emit:
        await emit("replace", {"content": content})
```

### 2.3 Citation Guard 规则

`citations_valid(citations)` 判定逻辑：

1. 至少一条有实质 `content`
2. 最高分 `score > rag_score_floor`（0.01）
3. 若来源为 `hybrid`/`keyword`（RRF 分）→ 直接通过
4. 否则需 `top >= rag_score_threshold`（0.35）或 top-gap ≥ `rag_score_min_gap`（0.004）或仅一条结果

**触发条件**：`knowledge_searched=True`（本轮调过 `knowledge_search`）且 intent 在 `CITATION_GUARD_INTENTS`。

**面试话术**：这是 **「检索了但不可信」** 的兜底，比「没检索」更严格——避免 LLM 拿低分 chunk 胡说。

### 2.4 collect_rag_citations

合并 `state.rag_citations` 与 `knowledge_search` 工具成功返回的 citations，按 `chunk_id` 去重——保证 guardrails 看到完整引用集。

### 2.5 CoT 脱敏

`redact_cot_traces()` 对观测 timeline 中的推理链做 `strip_banned_diagnosis`，防止 admin 在 Agent Runs 页看到未脱敏诊断词。

---

## 3. safety_review_node（回合内安全）

**文件**：`backend/app/agent/coach/nodes/safety_review.py`

与 guardrails **互补**：

| 层级 | 时机 | 行为 |
|------|------|------|
| safety_review | synthesize 之前 | 红旗关键词 + 可选 LLM JSON `blocked` |
| guardrails | synthesize 之后 | 输出清洗、引用、免责声明 |

红旗词扩展自 `SAFETY_KEYWORDS` + 昏厥、咳血、自杀等。拦截后走 `safety_blocked` 模板，benchmark 检查 `safety_review` step 或 `intent=safety`。

---

## 4. JWT 认证

### 4.1 为何自研而非 OAuth/OIDC？

Demo + 面试项目需要 **可读懂、零外部 IdP** 的认证；HMAC JWT 约 40 行，满足 Bearer 无状态 API。

### 4.2 令牌格式

```19:44:backend/app/auth/tokens.py
def create_access_token(payload: dict, expires_minutes=None) -> str:
    data["exp"] = int((datetime.now(UTC) + timedelta(minutes=expire_minutes)).timestamp())
    message = _b64url_encode(json.dumps(data, ...))
    signature = hmac.new(settings.auth_secret_key.encode(), message.encode(), hashlib.sha256).digest()
    return f"{message}.{signature}"

def decode_access_token(token: str) -> dict:
    # hmac.compare_digest 防时序攻击
    # 校验 exp
```

**Payload 字段**：`sub`（user UUID）、`role`（冗余，权威以 DB 为准）、`exp`。

**配置**：`AUTH_SECRET_KEY` 生产环境 min 32 字符，`validate_auth_secret_for_env()` 拒绝已知弱密钥。

### 4.3 认证依赖链

```22:57:backend/app/core/deps.py
async def get_current_user(credentials, db) -> User:
    payload = decode_access_token(token)
    user_id = uuid.UUID(payload["sub"])
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, ...)

def require_permissions(*required):
    async def checker(user = Depends(get_current_user)):
        permissions = get_user_permissions(user)
        missing = [p for p in required if p not in permissions]
        ...
```

`HTTPBearer(auto_error=False)` → 无 token 返回 401「缺少认证信息」。

### 4.4 密码与登录安全

| 机制 | 文件 | 说明 |
|------|------|------|
| 加盐哈希 | `auth/password.py` | 注册/创建用户 |
| 登录锁定 | `core/login_lockout.py` | 5 次/15 分钟（可配置） |
| 限流 | `core/rate_limit.py` | login/register/stream 分 scope |
| Bootstrap | `api/auth.py` | 首用户 advisory lock 创建 admin |

---

## 5. RBAC 三角色模型

### 5.1 权限字符串设计

采用 `resource:action` 或 `resource:action:scope` 形式，共 16 种权限（`ALL_PERMISSIONS`）。

### 5.2 角色矩阵

| 权限 | user | kb_editor | admin |
|------|:----:|:---------:|:-----:|
| `chat:send` | ✓ | ✓ | ✓ |
| `profile:read/write` | ✓ | ✓ | ✓ |
| `session:read/manage:own` | ✓ | ✓ | ✓ |
| `feedback:write` | ✓ | ✓ | ✓ |
| `knowledge:read/write/reindex` | — | ✓ | ✓ |
| `session:read/manage:all` | — | — | ✓ |
| `user:manage` | — | — | ✓ |
| `observability:read` | — | — | ✓ |
| `benchmark:run/read` | — | — | ✓ |

```1:38:backend/app/auth/permissions.py
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "user": { "chat:send", "profile:read", ... },
    "kb_editor": { ..., "knowledge:read", "knowledge:write", "knowledge:reindex" },
    "admin": { ..., "user:manage", "observability:read", "benchmark:run", "benchmark:read" },
}
```

### 5.3 自定义权限

`User.custom_permissions` 可在 admin 创建用户时附加；`validate_custom_permissions` 防止非法字符串。`resolve_user_permissions` = 角色默认 ∪ 自定义。

### 5.4 Demo 账号

| 用户名 | 角色 | 密码 |
|--------|------|------|
| `coach_demo` | user | `Demo@123456` |
| `kb_demo` | kb_editor | 同上 |
| `admin_demo` | admin | 同上 |

### 5.5 会话级 RBAC（Chat API）

除全局 permission 外，Chat 路由有 **资源归属** 检查：

```67:84:backend/app/api/chat.py
def _require_session_read(session, user, permissions):
    if "session:read:all" in permissions: return
    if session.user_id != user.id:
        raise HTTPException(403, "无权访问其他用户会话。")
```

admin 可读/manage 全会话；普通用户仅 own。Benchmark 会话对 Chat API **一律 403**。

### 5.6 前后端对齐

| 层 | 机制 |
|----|------|
| 后端 | `require_permissions("knowledge:read")` |
| 前端路由 | `PermissionRoute` + `usePermissions` |
| 前端导航 | `Sidebar` `visible` 过滤 |
| 契约 | `GET /auth/permissions` 返回 `PermissionMatrixResponse` |

---

## 6. 其他安全控制

| 控制 | 位置 | 说明 |
|------|------|------|
| CORS | `main.py` | `cors_origin_list()` 白名单 |
| Security Headers | `core/middleware.py` | XSS/CSP 等 |
| Trace ID | `TraceMiddleware` | 请求链路关联 |
| 错误脱敏 | `core/errors.py` | `PUBLIC_ERROR_MESSAGE` 隐藏内部栈 |
| 上传限制 | `config.max_upload_bytes` | 知识库 10MB |
| Benchmark 路径穿越 | `resolve_dataset_path` | 禁止 `..` 逃出 data/benchmark |

---

## 7. 代码锚点速查表

| 概念 | 路径 |
|------|------|
| 护栏核心 | `backend/app/agent/guardrails.py` |
| 护栏节点 | `backend/app/agent/coach/nodes/apply_guardrails.py` |
| 安全审查 | `backend/app/agent/coach/nodes/safety_review.py` |
| 权限表 | `backend/app/auth/permissions.py` |
| JWT | `backend/app/auth/tokens.py` |
| 依赖注入 | `backend/app/core/deps.py` |
| Auth API | `backend/app/api/auth.py` |
| 前端权限 | `frontend/src/contexts/AuthContext.tsx` |
| 路由守卫 | `frontend/src/router.tsx` |
| 测试 | `backend/tests/test_guardrails.py`, `test_auth.py`, `test_apply_guardrails_node.py` |

---

## 8. 常见追问

### Q1：Citation Guard 会不会误杀好回答？

**答**：仅当 **调用了 knowledge_search** 且分数不达标才替换为 FALLBACK；chitchat 未检索不受影响。阈值针对 hybrid RRF 分做了分支。

**追问链**
- *追问*：用户关闭 RAG 呢？  
  *答*：检索为空，通常不触发「检索了但不可信」；若 LLM 仍调用 knowledge_search 会得到空 citations，可能触发 guard。

### Q2：为何免责声明不放在 system prompt？

**答**：prompt 无法保证 100% 遵守；`ensure_disclaimer` 是确定性后处理，benchmark 可测 `must_include_disclaimer`。

**追问链**
- *追问*：重复免责声明怎么办？  
  *答*：`dedupe_disclaimer` 循环删除重复段。

### Q3：JWT 存 localStorage 安全吗？

**答**：Demo 权衡；面试应承认 XSS 风险，生产可改 httpOnly cookie + CSRF token 或短 token + refresh。

### Q4：role 在 JWT 和 DB 不一致怎么办？

**答**：鉴权以 DB `user.role` 经 `resolve_user_permissions` 为准；JWT 内 role 仅展示冗余，改角色后旧 token 仍有效直到过期——可追问「生产应缩短 TTL 或加 version 字段」。

### Q5：kb_editor 为何不能管用户？

**答**：职责分离：内容运营 vs 系统管理；降低误操作面。

### Q6：custom_permissions 使用场景？

**答**：例如给某 user 临时 `observability:read` 而不升 admin；面试作「可扩展点」提及即可。

### Q7：strip_banned_diagnosis vs 直接拒绝？

**答**：替换为【已省略】保留回答结构，避免整段拒答伤体验；严重安全问题由 safety_review **整段拦截**。

### Q8：如何做权限测试？

**答**：`test_auth.py` 覆盖登录/bootstrap；`test_knowledge_api.py` 分角色 403；前端靠三账号手动验收 Sidebar 与路由。

---

## 延伸阅读

- [08-前端与SSE](08-前端与SSE.md) — PermissionRoute 与 Sidebar
- [09-评测与观测](09-评测与观测.md) — safety_compliant 评测
- [05-RAG与Graph-RAG](05-RAG与Graph-RAG.md) — citation score 来源
- [../reference/ARCHITECTURE.md](../reference/ARCHITECTURE.md) — RBAC 架构图
- [../reference/COACH_ACCEPTANCE.md](../reference/COACH_ACCEPTANCE.md) — 安全验收项
