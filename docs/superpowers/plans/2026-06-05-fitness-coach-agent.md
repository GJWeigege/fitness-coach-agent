# Fitness Coach Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `fitness-coach-agent` full-stack application per `docs/COACH_AGENT_REDESIGN.md` v1.8 — LangGraph multi-agent coach with Planning, CoT, parallel recovery, RAG+Graph, benchmark, and SSE contract (passthrough `replace` / merge `delta`).

**Architecture:** FastAPI + async SQLAlchemy + pgvector backend; React/Vite frontend. `ChatService` owns messages and `done`; `CoachGraphOrchestrator` owns LangGraph runs and SSE through `synthesize`/`apply_guardrails`. Copy patterns from sibling repo `../customer-service-agent` but **exclude** handoff, tickets, orders, Legacy orchestrator.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2 async, Alembic, pgvector, LangGraph, DashScope API, pytest, React 18, Vite, TypeScript.

**Spec:** `docs/COACH_AGENT_REDESIGN.md` (v1.8) — authoritative for config defaults, SSE §3.6.1, tasks T-001…T-115.

**Reference repo:** `e:/work/D migrate/files/myself/projects/AI/customer-service-agent` — copy/adapt files listed per task; never copy CS knowledge markdown or business tools.

---

## File structure (create empty tree in T-001)

| Path | Responsibility |
|------|----------------|
| `backend/app/main.py` | FastAPI app, lifespan, router registration |
| `backend/app/core/config.py` | All §3.2 settings |
| `backend/app/core/deps.py` | DB session, current user, permissions |
| `backend/app/core/middleware.py` | Trace ID middleware |
| `backend/app/core/rate_limit.py` | In-memory rate limiter |
| `backend/app/core/login_lockout.py` | Login brute-force guard |
| `backend/app/core/errors.py` | HTTP exception handlers |
| `backend/app/db/models.py` | ORM §5 |
| `backend/app/db/session.py` | Async engine |
| `backend/app/llm/dashscope_client.py` | LLM + embedding client |
| `backend/app/services/*.py` | chat, memory, rag, ingest, graph, profile, benchmark, observability |
| `backend/app/agent/coach/state.py` | CoachState + reducers |
| `backend/app/agent/coach/graph.py` | LangGraph build |
| `backend/app/agent/coach/orchestrator.py` | stream_turn, finalize_run, SSE bridge |
| `backend/app/agent/coach/nodes/*.py` | Graph nodes |
| `backend/app/agent/intent_router.py` | CoachIntentRouter |
| `backend/app/agent/guardrails.py` | Safety + citation guards |
| `backend/app/agent/tools/*.py` | 7 coach tools + registry |
| `backend/app/prompts/coach/*.txt` | planner, cot, banned_diagnosis |
| `backend/app/api/*.py` | HTTP routes §6 |
| `backend/tests/**` | pytest mirror |
| `frontend/src/**` | pages, api, hooks, contexts |
| `docs/AGENT_SSE.md` | SSE protocol incl. §3.6.1 |
| `docker-compose.yml` | postgres pgvector, DB `fitness_coach` |

---

## Execution order (milestones)

```text
M1 T-001→006  →  M2 T-010→012  →  M3 T-020→024
→ M4 T-030→031  →  M5 T-040→041  →  M6 T-050→056→051→052→053
→ M7 T-060→061  →  M8 T-071→072→065→066→074→073→075→076
→ M9 T-080→083  →  M10 T-090→093  →  M11 T-102→104  →  M12 T-110→115
```

Run full suite after each milestone: `cd backend && pytest -q` and `cd frontend && pnpm run build`.

---

## M1 — Infrastructure

### Task 1: T-001 Repository & Docker

**Files:**
- Create: `docker-compose.yml`, `backend/requirements.txt`, `backend/.env.example`, `.gitignore`, `README.md` (stub)

- [ ] **Step 1: Create docker-compose**

```yaml
# docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: fitness_coach
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d fitness_coach"]
      interval: 5s
      timeout: 5s
      retries: 10
volumes:
  pgdata:
```

- [ ] **Step 2: Create requirements.txt**

```text
fastapi>=0.115.0
uvicorn[standard]>=0.32.0
sqlalchemy[asyncio]>=2.0.36
asyncpg>=0.30.0
alembic>=1.14.0
pgvector>=0.3.6
pydantic-settings>=2.6.0
python-multipart>=0.0.17
httpx>=0.28.0
langgraph>=0.2.0
pytest>=8.3.0
pytest-asyncio>=0.24.0
```

- [ ] **Step 3: Create `.env.example`** — copy every variable from design doc §3.2 (`APP_NAME=fitness-coach-agent`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/fitness_coach`, coach-specific models, `PARALLEL_SUB_AGENTS_ENABLED=true`, `LORA_ENABLED=false`, etc.).

- [ ] **Step 4: Verify**

Run: `docker compose up -d && docker compose ps`  
Expected: postgres healthy on 5432.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml backend/requirements.txt backend/.env.example .gitignore README.md
git commit -m "chore: scaffold repo, docker, and env template"
```

---

### Task 2: T-002 Backend skeleton

**Files:**
- Create: `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/core/deps.py`, `backend/app/__init__.py`
- Reference: `customer-service-agent/backend/app/main.py`, `core/config.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_health.py
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app

@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd backend && pip install -r requirements.txt && pytest tests/test_health.py -v`  
Expected: FAIL (no app)

- [ ] **Step 3: Implement config + main**

`backend/app/core/config.py` — class `Settings` with all §3.2 fields; add `validate_auth_secret()` raising if production and secret &lt; 32 chars (mirror reference repo).

`backend/app/main.py` — lifespan: validate settings, optional dev seed hook; `GET /health`; CORS from settings; include routers placeholder.

- [ ] **Step 4: Run test — expect PASS**

Run: `pytest tests/test_health.py -v`

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: backend skeleton with config and health endpoint"
```

---

### Task 3: T-003 Frontend skeleton

**Files:**
- Create: `frontend/` via `pnpm create vite@latest frontend -- --template react-ts`
- Create: `frontend/src/layouts/MainLayout.tsx`, `frontend/src/router.tsx`, stub pages

- [ ] **Step 1: Scaffold Vite project**
- [ ] **Step 2: Add router + layout shell** (AuthPage, ChatPage placeholders)
- [ ] **Step 3: Verify** — `cd frontend && pnpm install && pnpm run build`
- [ ] **Step 4: Commit** — `feat: frontend vite skeleton with layout and routes`

---

### Task 4: T-004 ORM + migration

**Files:**
- Create: `backend/app/db/models.py`, `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/0001_initial.py`
- Reference: `customer-service-agent/backend/app/db/models.py` — **drop** Ticket, handoff fields on ChatSession, human_agent_id on ChatMessage; **add** UserProfile, TrainingLog, graph_*, benchmark_*

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_models_import.py
def test_all_tables_registered():
    from app.db import models
    names = {t.name for t in models.Base.metadata.tables.values()}
    assert "users" in names
    assert "user_profiles" in names
    assert "graph_entities" in names
    assert "benchmark_runs" in names
    assert "tickets" not in names
```

- [ ] **Step 2: Implement models per design §5**
- [ ] **Step 3: Generate migration** — `alembic revision --autogenerate -m "initial"` → rename to `0001_initial.py`; review SQL includes pgvector extension.
- [ ] **Step 4: Run migration in test** — conftest will use this in T-006; manual: `alembic upgrade head`
- [ ] **Step 5: Commit** — `feat: add ORM models and initial migration`

---

### Task 5: T-005 Middleware

**Files:**
- Create: `backend/app/core/middleware.py`, `rate_limit.py`, `login_lockout.py`, `errors.py`
- Create: `backend/tests/test_rate_limit.py`, `test_login_lockout.py`
- Reference: copy from `customer-service-agent/backend/app/core/*`

- [ ] **Step 1: Copy and adapt middleware tests from reference**
- [ ] **Step 2: Wire middleware in `main.py`**
- [ ] **Step 3: Run** — `pytest tests/test_rate_limit.py tests/test_login_lockout.py -v`
- [ ] **Step 4: Commit** — `feat: trace, rate limit, login lockout middleware`

---

### Task 6: T-006 Test infrastructure

**Files:**
- Create: `backend/tests/conftest.py`, `backend/pytest.ini`
- Reference: `customer-service-agent/backend/tests/` patterns

- [ ] **Step 1: conftest with async DB**

```python
# backend/tests/conftest.py (minimal core)
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.main import app
from app.db.models import Base
from app.core.deps import get_db

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/fitness_coach_test"

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()

@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Create test DB** — `CREATE DATABASE fitness_coach_test;`
- [ ] **Step 3: Run** — `pytest -q`
- [ ] **Step 4: Commit** — `test: add async pytest conftest and fixtures`

---

## M2 — Auth (T-010, T-011, T-012)

### Task 7: T-010 Auth backend

**Files:**
- Create: `backend/app/auth/password.py`, `tokens.py`, `permissions.py` (§4 ROLE_PERMISSIONS)
- Create: `backend/app/api/auth.py`, `backend/app/schemas/auth.py`
- Create: `backend/tests/test_auth.py`
- Reference: `customer-service-agent/backend/app/auth/*`, `api/auth.py` — change default role to `user`

- [ ] **Step 1: test register/login/me with RBAC matrix**
- [ ] **Step 2: Implement auth API**
- [ ] **Step 3: `pytest tests/test_auth.py -v`**
- [ ] **Step 4: Commit** — `feat: auth API with coach RBAC`

### Task 8: T-011 Auth frontend

**Files:** `frontend/src/contexts/AuthContext.tsx`, `frontend/src/pages/AuthPage.tsx`, `frontend/src/api/auth.ts`

- [ ] **Step 1: Login form → store token**
- [ ] **Step 2: Protected routes redirect**
- [ ] **Step 3: Manual verify in browser**
- [ ] **Step 4: Commit** — `feat: auth page and context`

### Task 9: T-012 Demo seed

**Files:** `backend/scripts/seed_demo_data.py`, `backend/app/db/seed_users.py`

- [ ] **Step 1: Seed `coach_demo`, `admin_demo`, `kb_demo` / `Demo@123456`**
- [ ] **Step 2: Wire in lifespan when `APP_ENV=dev`**
- [ ] **Step 3: Commit** — `chore: demo user seed`

---

## M3 — RAG (T-020 … T-024)

### Task 10: T-020 DashScope client

**Files:** `backend/app/llm/dashscope_client.py`, `backend/tests/test_dashscope.py`  
**Reference:** `customer-service-agent/backend/app/llm/dashscope_client.py`

- [ ] **Step 1: Mock httpx test for chat, chat_stream, chat_stream_with_tools, embedding**
- [ ] **Step 2: Implement timeout + retry from `LLM_REQUEST_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`**
- [ ] **Step 3: `pytest tests/test_dashscope.py -v`**
- [ ] **Step 4: Commit** — `feat: dashscope client with retry`

### Task 11: T-021 Ingest

**Files:** `backend/app/services/ingest_service.py`, `backend/tests/test_ingest.py`

- [ ] **Step 1: Test chunk + embed pipeline (mock embedding)**
- [ ] **Step 2: Implement with `INGEST_CHUNK_SIZE`, `INGEST_CHUNK_OVERLAP`**
- [ ] **Step 3: Commit** — `feat: document ingest service`

### Task 12: T-022 RAG

**Files:** `backend/app/services/rag_service.py`, `backend/tests/test_rag.py`

- [ ] **Step 1: Hybrid vector + keyword test**
- [ ] **Step 2: Implement `RAG_HYBRID_ENABLED`, thresholds from §3.2**
- [ ] **Step 3: Commit** — `feat: hybrid RAG service`

### Task 13: T-023 Knowledge seed

**Files:** `backend/data/knowledge/*.md` (5 files per §3.8), `backend/app/db/seed_knowledge.py`

- [ ] **Step 1: Write coach domain markdown (not CS docs)**
- [ ] **Step 2: Seed script ingests on startup/dev**
- [ ] **Step 3: Commit** — `chore: coach knowledge base seed`

### Task 14: T-024 Knowledge API + UI

**Files:** `backend/app/api/knowledge.py`, `frontend/src/pages/KnowledgePage.tsx`, `backend/tests/test_knowledge_api.py`

- [ ] **Step 1: Upload + list + reindex with rate_limit**
- [ ] **Step 2: Frontend page for kb_editor role**
- [ ] **Step 3: Commit** — `feat: knowledge management API and UI`

---

## M4 — Memory & Chat CRUD (T-030, T-031)

### Task 15: T-030 Memory service

**Files:** `backend/app/services/memory_service.py`, `backend/tests/test_memory.py`, `backend/tests/test_long_context_mode.py`

- [ ] **Step 1: Test sliding window + summary trigger**
- [ ] **Step 2: Implement `LONG_CONTEXT_MODE=summary|full` branch (full uses `COACH_LONG_CONTEXT_MODEL` in message builder)**
- [ ] **Step 3: Commit** — `feat: memory service with long context mode`

### Task 16: T-031 Chat CRUD + feedback

**Files:** `backend/app/services/chat_session_service.py`, `backend/app/api/chat.py` (sessions/messages/feedback only — **no stream yet**), `backend/tests/test_chat_sessions.py`, `backend/tests/test_message_feedback.py`

- [ ] **Step 1: Session CRUD scoped to user_id UUID FK**
- [ ] **Step 2: Message list + feedback up/down**
- [ ] **Step 3: rate_limit on write endpoints**
- [ ] **Step 4: Commit** — `feat: chat sessions, messages, feedback`

---

## M5 — Profile (T-040, T-041)

### Task 17: T-040 Profile API

**Files:** `backend/app/services/profile_service.py`, `backend/app/api/profile.py`, `backend/tests/test_profile.py`

- [ ] **Step 1: GET/PUT profile + training-logs CRUD**
- [ ] **Step 2: Commit** — `feat: user profile and training logs API`

### Task 18: T-041 Profile UI

**Files:** `frontend/src/pages/ProfilePage.tsx`, `frontend/src/api/profile.ts`

- [ ] **Step 1: Form for §5.2 fields**
- [ ] **Step 2: Commit** — `feat: profile page`

---

## M6 — Tools & Guardrails (T-050, T-055, T-056, T-051, T-052, T-053)

### Task 19: T-050 Intent router

**Files:** `backend/app/agent/intent_router.py`, `backend/app/prompts/coach/router.txt`, `backend/tests/test_intent.py` (≥10 cases)

- [ ] **Step 1: Test intents: training, nutrition, recovery, safety, profile, chitchat, unknown**
- [ ] **Step 2: `CoachIntentRouter.route()` returns intent + active_agents (recovery → `["training","nutrition"]`)**
- [ ] **Step 3: Commit** — `feat: coach intent router`

### Task 20: T-055 Planner node logic (pure functions first)

**Files:** `backend/app/agent/coach/plan_schema.py`, `backend/app/prompts/coach/planner.txt`, `backend/tests/test_plan_execute.py`

- [ ] **Step 1: Pydantic schema for execution_plan**
- [ ] **Step 2: Test parse + validate tasks ⊆ active_agents; fallback on invalid JSON**
- [ ] **Step 3: Commit** — `feat: plan schema and parser`

### Task 21: T-056 CoT parser

**Files:** `backend/app/agent/coach/cot.py`, `backend/app/prompts/coach/cot_instruction.txt`, `backend/tests/test_cot_parse.py`

```python
# backend/app/agent/coach/cot.py
import re
REASONING_RE = re.compile(r"<reasoning>(.*?)</reasoning>", re.DOTALL)

def split_cot(text: str) -> tuple[str | None, str]:
    m = REASONING_RE.search(text)
    if not m:
        return None, text.strip()
    reasoning = m.group(1).strip()
    answer = REASONING_RE.sub("", text).strip()
    return reasoning, answer
```

- [ ] **Step 1: Test split + strip**
- [ ] **Step 2: Commit** — `feat: cot reasoning parser`

### Task 22: T-051 Guardrails

**Files:** `backend/app/agent/guardrails.py`, `backend/app/prompts/coach/banned_diagnosis.txt`, `backend/tests/test_guardrails.py`

- [ ] **Step 1: Tests for disclaimer, banned words, citation required when knowledge_search used**
- [ ] **Step 2: cot_traces redaction helper**
- [ ] **Step 3: Commit** — `feat: coach guardrails`

### Task 23: T-052 Seven tools

**Files:** `backend/app/agent/tools/knowledge.py`, `contraindication.py`, `profile.py`, `training_log.py`, `macros.py`, `alternatives.py`, `graph_lookup.py`, `backend/tests/test_coach_tools.py`

- [ ] **Step 1: One test per tool with ToolContext mock**
- [ ] **Step 2: Implement each per §3.8.1**
- [ ] **Step 3: Commit** — `feat: seven coach agent tools`

### Task 24: T-053 Tool registry

**Files:** `backend/app/agent/tools/registry.py`, `backend/tests/test_registry.py`

- [ ] **Step 1: CoachToolRegistry + ToolContext dataclass from §3.4.7**
- [ ] **Step 2: Commit** — `feat: coach tool registry`

---

## M7 — Graph (T-060, T-061)

### Task 25: T-060 GraphService

**Files:** `backend/app/services/graph_service.py`, `backend/app/db/seed_graph.py`, `backend/tests/test_graph.py`

- [ ] **Step 1: Seed entities/edges for coach domain**
- [ ] **Step 2: link_entities + 1-hop query**
- [ ] **Step 3: Commit** — `feat: graph service and seed`

### Task 26: T-061 Graph + RAG injection

**Files:** modify `backend/app/agent/coach/nodes/build_llm_messages.py` (or shared helper)

- [ ] **Step 1: Test graph_context appended to system when `GRAPH_RAG_ENABLED`**
- [ ] **Step 2: Commit** — `feat: graph context injection for RAG`

---

## M8 — LangGraph core (T-071, T-072, T-065, T-066, T-074, T-073, T-075, T-076)

### Task 27: T-071 Graph definition

**Files:** `backend/app/agent/coach/state.py`, `backend/app/agent/coach/graph.py`, `backend/tests/test_coach_graph.py`

- [ ] **Step 1: state.py with Annotated reducers (§3.4.1)**
- [ ] **Step 2: graph.py wires nodes + conditional edges per §3.4.2 mermaid**
- [ ] **Step 3: Test graph compiles and reaches END on mocked nodes**
- [ ] **Step 4: Commit** — `feat: langgraph coach state and graph skeleton`

### Task 28: T-072 Graph nodes

**Files:** `backend/app/agent/coach/nodes/load_profile.py`, `route_intent.py`, `plan_execute.py`, `sub_agent.py`, `coach_chitchat.py`, `safety_review.py`, `synthesize.py`, `apply_guardrails.py`, `persist_turn.py`, `knowledge_prefetch.py`, `build_llm_messages.py`  
**Tests:** `backend/tests/test_sub_agent_react.py`, `test_build_llm_messages.py`

**synthesize SSE (critical — §3.4.6, §3.6.1):**

```python
# backend/app/agent/coach/nodes/synthesize.py (behavior sketch)
async def synthesize_node(state, config):
    ctx = config["configurable"]
    if state["safety_blocked"]:
        state["final_answer"] = SAFETY_TEMPLATE
        await ctx["emit"]("replace", {"content": state["final_answer"]})
        return state
    if len(state.get("active_agents") or []) >= 2:
        text = ""
        async for chunk in ctx["llm"].chat_stream(messages):
            text += chunk
            await ctx["emit"]("delta", {"content": chunk})
        state["final_answer"] = text
        return state
    # passthrough
    answer = next(iter(state["agent_outputs"].values()), "")
    state["final_answer"] = answer
    await ctx["emit"]("replace", {"content": answer})
    return state
```

- [ ] **Step 1: build_llm_messages test with 3-turn history mock**
- [ ] **Step 2: sub_agent ReAct loop with CoT parse**
- [ ] **Step 3: synthesize tests: passthrough emits replace only; recovery emits deltas**
- [ ] **Step 4: Commit** — `feat: coach graph nodes including synthesize SSE`

### Task 29: T-065 Parallel dispatch

**Files:** `backend/app/agent/coach/nodes/dispatch_sub_agents.py`, `backend/tests/test_parallel_recovery.py`

- [ ] **Step 1: LangGraph Send fan-out for parallel_group=0**
- [ ] **Step 2: Assert both agent_outputs keys populated; parallel_agents_used=true**
- [ ] **Step 3: Commit** — `feat: parallel sub-agent dispatch with Send`

### Task 30: T-066 Serial fallback

**Files:** same graph conditional on `PARALLEL_SUB_AGENTS_ENABLED`

- [ ] **Step 1: test_recovery_serial_fallback.py**
- [ ] **Step 2: Commit** — `feat: serial recovery fallback when parallel disabled`

### Task 31: T-074 Observability service

**Files:** `backend/app/services/observability_service.py`, `backend/tests/test_obs_svc.py`

- [ ] **Step 1: create_run, append_step, finish_run, list_runs**
- [ ] **Step 2: Commit** — `feat: observability service`

### Task 32: T-073 Orchestrator + AGENT_SSE.md

**Files:** `backend/app/agent/coach/orchestrator.py`, `docs/AGENT_SSE.md`, `backend/tests/test_sse_bridge.py`, `test_degraded.py`, `test_resilience.py`

- [ ] **Step 1: Write `docs/AGENT_SSE.md`** — copy event types + add §3.6.1 table from design doc
- [ ] **Step 2: CoachGraphOrchestrator.stream_turn bridges LangGraph → SSE; yields `result` last**
- [ ] **Step 3: finalize_run writes tool_calls, execution_plan, parallel_agents_used to steps**
- [ ] **Step 4: test_sse_bridge: single-agent → replace only; recovery → delta before done**
- [ ] **Step 5: Commit** — `feat: coach orchestrator and SSE bridge`

### Task 33: T-075 ChatService

**Files:** `backend/app/services/chat_service.py`, `backend/app/api/chat.py` (stream/send), `backend/tests/test_chat_stream.py`

**Six-step contract §3.5:**

```python
# Pseudocode — chat_service.stream_message
async def stream_message(...):
    # 1 persist user + increment_turn_count + commit
    events = []
    async for ev in orchestrator.stream_turn(...):
        if ev["type"] == "result":
            result = CoachRunResult(**ev)
            continue
        yield ev
    # 3 persist assistant from result.final_answer
    # 4 maybe_update_summary
    # 5 orchestrator.finalize_run(...)
    # 6 yield done  (only here)
```

- [ ] **Step 1: test done comes after assistant row in DB**
- [ ] **Step 2: test single-agent stream has zero delta events**
- [ ] **Step 3: send_message aggregates last replace or joins deltas**
- [ ] **Step 4: Commit** — `feat: chat service six-step lifecycle`

### Task 34: T-076 Observability API

**Files:** `backend/app/api/observability.py`, `backend/app/schemas/observability.py`, `backend/tests/test_observability_api.py`

- [ ] **Step 1: GET runs + run detail with steps payload**
- [ ] **Step 2: Commit** — `feat: observability API`

---

## M9 — Frontend (T-080 … T-083)

### Task 35: T-080 Chat UI

**Files:** `frontend/src/pages/ChatPage.tsx`, `frontend/src/hooks/useSessions.ts`, `frontend/src/api/chat.ts`

```typescript
// frontend/src/hooks/useSessions.ts (SSE handler core)
case "delta":
  appendToLastAssistant(event.content);
  break;
case "replace":
  replaceLastAssistant(event.content);
  break;
```

- [ ] **Step 1: Implement replace/delta per §3.6.1**
- [ ] **Step 2: Manual E2E: case #3 no delta; case #2 shows delta stream**
- [ ] **Step 3: Commit** — `feat: chat page SSE replace and delta handling`

### Task 36: T-081 Agent runs UI

**Files:** `frontend/src/pages/AgentRunsPage.tsx` — timeline of steps incl. planning, cot payload

- [ ] **Commit** — `feat: agent runs observability page`

### Task 37: T-082 Users admin UI

**Files:** `frontend/src/pages/UsersPage.tsx`

- [ ] **Commit** — `feat: admin users page`

### Task 38: T-083 Sidebar RBAC

**Files:** `frontend/src/components/layout/Sidebar.tsx` — hide Knowledge until kb_editor+

- [ ] **Commit** — `feat: permission-aware sidebar`

---

## M10 — Benchmark (T-090 … T-093)

### Task 39: T-090 Benchmark dataset

**Files:** `backend/data/benchmark/coach_eval.jsonl` (≥30 dev, target 80)

- [ ] **Step 1: JSONL validator script or pytest for schema fields incl. expected_plan_agents**
- [ ] **Step 2: Commit** — `chore: benchmark evaluation dataset`

### Task 40: T-091 Benchmark runner

**Files:** `backend/app/services/benchmark_runner.py`, `backend/tests/test_benchmark.py`

- [ ] **Step 1: Metrics: intent_accuracy, plan_agent_recall, citation_rate, tool_recall, safety_compliance, latency_p95**
- [ ] **Step 2: Read plan from planning step payload for plan_agent_recall**
- [ ] **Step 3: Commit** — `feat: benchmark runner and metrics`

### Task 41: T-092 Benchmark API

**Files:** `backend/app/api/benchmark.py`, `backend/app/services/benchmark_service.py`

- [ ] **Step 1: POST 202 + BackgroundTasks status machine pending→running→completed|failed**
- [ ] **Step 2: Commit** — `feat: benchmark API`

### Task 42: T-093 Benchmark dashboard UI

**Files:** `frontend/src/pages/BenchmarkDashboardPage.tsx`

- [ ] **Commit** — `feat: benchmark dashboard with polling`

---

## M11 — Systems (T-102, T-103, T-104)

### Task 43: T-102 Background tasks

- [ ] Wire upload reindex + benchmark runs via FastAPI BackgroundTasks
- [ ] **Commit** — `feat: background tasks for ingest and benchmark`

### Task 44: T-103 k6 + HA doc

**Files:** `scripts/load/chat_stream.js`, `docs/COACH_HA.md`

- [ ] **Commit** — `docs: HA notes and k6 load script`

### Task 45: T-104 Metrics extension

**Files:** extend observability summary endpoint

- [ ] **Commit** — `feat: agent summary metrics`

---

## M12 — Documentation & LoRA (T-110 … T-115)

### Task 46: T-110 README + ARCHITECTURE

**Files:** `README.md`, `docs/ARCHITECTURE.md` — full run instructions

- [ ] **Commit** — `docs: README and architecture`

### Task 47: T-111 Acceptance checklist

**Files:** `docs/COACH_ACCEPTANCE.md` — copy §10 + §10.1 from design doc

- [ ] **Commit** — `docs: acceptance checklist`

### Task 48: T-112 Resume blurb

- [ ] Add ≤200 char project summary to README appendix
- [ ] **Commit** — `docs: resume appendix`

### Task 49: T-113 LLM architecture doc

**Files:** `docs/LLM_ARCHITECTURE.md` — §3.14.1 content

- [ ] **Commit** — `docs: LLM architecture and RAG rationale`

### Task 50: T-114 Long context experiment

- [ ] Run summary vs full on 20-turn fixture; record numbers in LLM_ARCHITECTURE.md
- [ ] **Commit** — `docs: long context mode comparison`

### Task 51: T-115 LoRA pipeline (dry-run)

**Files:** `backend/data/finetune/coach_sft.jsonl`, `backend/scripts/finetune_lora.py`, `backend/scripts/eval_lora.py`, `docs/LLM_FINETUNE_EXPERIMENT.md`

- [ ] **Step 1: Scripts accept `--dry-run` printing config**
- [ ] **Step 2: Document local vLLM path only; `LORA_ENABLED=false` default**
- [ ] **Commit** — `chore: lora experiment scripts and doc`

---

## Final verification (design §10)

- [ ] `cd backend && pytest -q` — all green
- [ ] `cd frontend && pnpm run lint && pnpm run build`
- [ ] Manual §10.1 cases #1–#5 in browser
- [ ] Benchmark ≥80 samples meets §3.10 thresholds
- [ ] Confirm no tickets/handoff code paths exist: `rg -i "handoff|ticket" backend/app` → empty

---

## Spec coverage self-review

| Spec section | Plan tasks |
|--------------|------------|
| §3.5 ChatService/Orchestrator split | T-075, T-073 |
| §3.4.2 Parallel Send | T-065, T-066 |
| §3.4.5 Planning | T-055, T-072 plan_execute node |
| §3.13 CoT | T-056, T-072 |
| §3.6.1 SSE replace/delta | T-072 synthesize, T-073, T-075, T-080 |
| §3.8 RAG + 7 tools | T-022, T-052, T-053 |
| §3.9 Graph | T-060, T-061 |
| §3.10 Benchmark | T-090–093 |
| §3.14 LoRA / long context | T-030, T-114, T-115 |
| §4 RBAC | T-010, T-083 |
| §10 Acceptance | T-111 + Final verification |

**Placeholder scan:** None — all tasks name concrete files and tests.

**Type consistency:** `CoachRunResult`, `ToolContext`, `CoachState` defined before orchestrator tasks; SSE event keys `type`, `content` consistent with AGENT_SSE.md.

---

## Reference copy map (quick)

| Coach file | Copy from CS repo |
|------------|-------------------|
| `core/middleware.py` | same path |
| `core/rate_limit.py` | same path |
| `llm/dashscope_client.py` | same path, add coach model settings |
| `services/rag_service.py` | same path |
| `services/memory_service.py` | same path, add LONG_CONTEXT_MODE |
| `auth/*` | same path, update ROLE_PERMISSIONS |
| **Do not copy** | `handoff_service.py`, `orchestrator.py`, `tools/business.py`, CS knowledge md |
