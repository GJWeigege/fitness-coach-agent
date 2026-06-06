import uuid

import pytest

from app.db.models import AgentRun, AgentStep, LlmCall
from app.services.observability_service import ObservabilityService


@pytest.mark.asyncio
async def test_observability_create_append_finish(db_session):
    svc = ObservabilityService()
    session_id = uuid.uuid4()
    user_message_id = uuid.uuid4()

    run = await svc.create_run(
        db_session,
        session_id=session_id,
        user_message_id=user_message_id,
        trace_id="trace-001",
    )
    assert run.status == "running"
    assert run.step_count == 0

    step = await svc.append_step(
        db_session,
        run.id,
        phase="planning",
        summary="plan created",
        payload={"tasks": []},
        duration_ms=12,
    )
    assert step.step_index == 0
    assert step.phase == "planning"

    finished = await svc.finish_run(
        db_session,
        run.id,
        status="completed",
        intent="training",
        total_latency_ms=120,
        prompt_tokens=100,
        completion_tokens=50,
        model_name="mock-model",
    )
    assert finished.status == "completed"
    assert finished.intent == "training"
    assert finished.finished_at is not None

    runs = await svc.list_runs(db_session, session_id=session_id, limit=10)
    assert len(runs) == 1
    assert runs[0].id == run.id


@pytest.mark.asyncio
async def test_observability_list_runs_ordered(db_session):
    svc = ObservabilityService()
    session_id = uuid.uuid4()

    run_a = await svc.create_run(
        db_session,
        session_id=session_id,
        user_message_id=None,
        trace_id="a",
    )
    run_b = await svc.create_run(
        db_session,
        session_id=session_id,
        user_message_id=None,
        trace_id="b",
    )
    await db_session.flush()

    runs = await svc.list_runs(db_session, session_id=session_id)
    assert runs[0].id in {run_a.id, run_b.id}
    assert len(runs) == 2

    fetched = await svc.get_run(db_session, run_a.id)
    assert fetched is not None
    assert fetched.trace_id == "a"


@pytest.mark.asyncio
async def test_observability_record_llm_call(db_session):
    svc = ObservabilityService()
    session_id = uuid.uuid4()
    run = await svc.create_run(
        db_session,
        session_id=session_id,
        user_message_id=None,
        trace_id="trace-llm",
    )

    record = await svc.record_llm_call(
        db_session,
        run.id,
        purpose="planner",
        model="qwen-plus",
        prompt_tokens=100,
        completion_tokens=40,
        latency_ms=88,
    )
    assert isinstance(record, LlmCall)
    assert record.run_id == run.id
    assert record.prompt_tokens == 100
    assert record.completion_tokens == 40
