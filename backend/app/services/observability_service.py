import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, AgentStep, LlmCall


class ObservabilityService:
    async def create_run(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID,
        user_message_id: uuid.UUID | None,
        trace_id: str,
    ) -> AgentRun:
        run = AgentRun(
            trace_id=trace_id,
            session_id=session_id,
            user_message_id=user_message_id,
            status="running",
            step_count=0,
        )
        db.add(run)
        await db.flush()
        return run

    async def append_step(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
        *,
        phase: str,
        summary: str | None = None,
        payload: dict | None = None,
        duration_ms: int | None = None,
        status: str = "ok",
    ) -> AgentStep:
        run = await db.get(AgentRun, run_id)
        step_index = run.step_count if run is not None else 0
        step = AgentStep(
            run_id=run_id,
            step_index=step_index,
            phase=phase,
            summary=summary,
            payload=payload,
            duration_ms=duration_ms,
            status=status,
        )
        if run is not None:
            run.step_count = step_index + 1
        db.add(step)
        await db.flush()
        return step

    async def record_llm_call(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
        *,
        purpose: str,
        model: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        latency_ms: int | None = None,
        step_id: uuid.UUID | None = None,
    ) -> LlmCall:
        record = LlmCall(
            run_id=run_id,
            step_id=step_id,
            purpose=purpose,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )
        db.add(record)
        await db.flush()
        return record

    async def finish_run(
        self,
        db: AsyncSession,
        run_id: uuid.UUID,
        *,
        status: str,
        intent: str | None = None,
        assistant_message_id: uuid.UUID | None = None,
        total_latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        model_name: str | None = None,
        memory_compacted: bool = False,
        dropped_message_count: int = 0,
        memory_summary_updated: bool = False,
        error_message: str | None = None,
    ) -> AgentRun:
        run = await db.get(AgentRun, run_id)
        if run is None:
            raise ValueError(f"agent run not found: {run_id}")

        run.status = status
        run.intent = intent
        run.assistant_message_id = assistant_message_id
        run.total_latency_ms = total_latency_ms
        run.prompt_tokens = prompt_tokens
        run.completion_tokens = completion_tokens
        run.model_name = model_name
        run.memory_compacted = memory_compacted
        run.dropped_message_count = dropped_message_count
        run.memory_summary_updated = memory_summary_updated
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        await db.flush()
        return run

    async def list_runs(
        self,
        db: AsyncSession,
        *,
        session_id: uuid.UUID | None = None,
        limit: int = 50,
    ) -> list[AgentRun]:
        stmt = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit)
        if session_id is not None:
            stmt = stmt.where(AgentRun.session_id == session_id)
        return list((await db.scalars(stmt)).all())

    async def get_run(self, db: AsyncSession, run_id: uuid.UUID) -> AgentRun | None:
        return await db.get(AgentRun, run_id)
