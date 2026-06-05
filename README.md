# Fitness Coach Agent

Multi-agent sports-health coach powered by LangGraph, RAG (pgvector), and DashScope Qwen. See [docs/COACH_AGENT_REDESIGN.md](docs/COACH_AGENT_REDESIGN.md) for the full design.

## Quick start

### 1. Database (Docker)

```bash
docker compose up -d
```

Starts PostgreSQL 16 + pgvector on `localhost:5432` (database `fitness_coach`).

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
copy .env.example .env          # cp on Unix
```

Set in `backend/.env`:

- `DASHSCOPE_API_KEY` — required for chat, embedding, and agent
- `AUTH_SECRET_KEY` — min 32 chars (auto-validated in production)

Run migrations (first time):

```bash
alembic upgrade head
```

Start API:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

OpenAPI: http://localhost:8000/docs

### 3. Frontend

```bash
cd frontend
pnpm install
pnpm run dev
```

App: http://localhost:5173

### 4. Demo accounts

In `APP_ENV=dev` or `test`, startup seeds demo users, knowledge (5 md files), and graph entities. Password for all: **`Demo@123456`**

| Username | Role | Capabilities |
|----------|------|--------------|
| `coach_demo` | user | Chat, profile, feedback |
| `kb_demo` | kb_editor | + knowledge upload/reindex |
| `admin_demo` | admin | + users, observability, benchmark |

Manual seed:

```bash
cd backend
python scripts/seed_demo_data.py
python scripts/seed_demo_data.py --users-only
python scripts/seed_demo_data.py --knowledge-only
```

## Verification

```bash
cd backend && pytest -q
cd frontend && pnpm run lint && pnpm run build
```

Load test (optional, requires [k6](https://k6.io)):

```bash
k6 run scripts/load/chat_stream.js -e BASE_URL=http://localhost:8000 -e TOKEN=<jwt>
```

## Documentation

| Doc | Purpose |
|-----|---------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layering, data flow, RBAC |
| [docs/AGENT_SSE.md](docs/AGENT_SSE.md) | SSE event contract |
| [docs/COACH_ACCEPTANCE.md](docs/COACH_ACCEPTANCE.md) | Release checklist |
| [docs/LLM_ARCHITECTURE.md](docs/LLM_ARCHITECTURE.md) | Transformer, RAG, long context |
| [docs/LLM_FINETUNE_EXPERIMENT.md](docs/LLM_FINETUNE_EXPERIMENT.md) | LoRA dry-run pipeline |
| [docs/COACH_HA.md](docs/COACH_HA.md) | HA notes + k6 |

## Core features

- **Multi-agent graph**: intent routing → planning → parallel sub-agents → synthesize
- **7 coach tools**: knowledge search, contraindication, profile, macros, training log, alternatives, graph lookup
- **RAG + Graph RAG**: hybrid vector + keyword retrieval
- **Memory**: sliding window + session summary (`LONG_CONTEXT_MODE=summary|full`)
- **Benchmark**: 36+ labeled samples, async runner, admin dashboard
- **Observability**: agent run timeline, metrics summary

No handoff / ticket / customer-service modules in this repo.
