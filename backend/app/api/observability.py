import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_permissions
from app.db.models import AgentRun, AgentStep, User
from app.schemas.observability import (
    AgentRunDetailResponse,
    AgentRunListItem,
    AgentRunListResponse,
    AgentStepItem,
)


router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/runs", response_model=AgentRunListResponse)
async def list_runs(
    session_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions("observability:read")),
) -> AgentRunListResponse:
    stmt = select(AgentRun).order_by(AgentRun.created_at.desc())
    count_stmt = select(func.count()).select_from(AgentRun)
    if session_id is not None:
        stmt = stmt.where(AgentRun.session_id == session_id)
        count_stmt = count_stmt.where(AgentRun.session_id == session_id)
    if status is not None:
        stmt = stmt.where(AgentRun.status == status)
        count_stmt = count_stmt.where(AgentRun.status == status)
    total = await db.scalar(count_stmt) or 0
    rows = list((await db.scalars(stmt.offset(offset).limit(limit))).all())
    return AgentRunListResponse(
        runs=[
            AgentRunListItem(
                id=r.id,
                trace_id=r.trace_id,
                session_id=r.session_id,
                intent=r.intent,
                status=r.status,
                step_count=r.step_count,
                total_latency_ms=r.total_latency_ms,
                model_name=r.model_name,
                memory_summary_updated=r.memory_summary_updated,
                created_at=r.created_at,
                finished_at=r.finished_at,
            )
            for r in rows
        ],
        total=total,
    )


@router.get("/runs/{run_id}", response_model=AgentRunDetailResponse)
async def get_run_detail(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions("observability:read")),
) -> AgentRunDetailResponse:
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在。")
    steps = list(
        (
            await db.scalars(
                select(AgentStep)
                .where(AgentStep.run_id == run_id)
                .order_by(AgentStep.step_index.asc())
            )
        ).all()
    )
    timeline = [
        AgentStepItem(
            id=s.id,
            step_index=s.step_index,
            phase=s.phase,
            summary=s.summary,
            payload=s.payload,
            duration_ms=s.duration_ms,
            status=s.status,
            created_at=s.created_at,
        )
        for s in steps
    ]
    return AgentRunDetailResponse(
        id=run.id,
        trace_id=run.trace_id,
        session_id=run.session_id,
        user_message_id=run.user_message_id,
        assistant_message_id=run.assistant_message_id,
        intent=run.intent,
        status=run.status,
        step_count=run.step_count,
        total_latency_ms=run.total_latency_ms,
        error_message=run.error_message,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        model_name=run.model_name,
        memory_compacted=run.memory_compacted,
        dropped_message_count=run.dropped_message_count,
        memory_summary_updated=run.memory_summary_updated,
        created_at=run.created_at,
        finished_at=run.finished_at,
        timeline=timeline,
    )
