import uuid

import pytest

from app.agent.coach.token_usage import (
    accumulate_tokens,
    combined_total_tokens,
    merge_token_counts,
    token_totals,
    track_llm_usage,
)
from app.db.models import LlmCall
from app.services.observability_service import ObservabilityService
from sqlalchemy import select


def test_accumulate_tokens_sums_across_calls():
    run_meta: dict = {}
    accumulate_tokens(run_meta, prompt_tokens=10, completion_tokens=5)
    accumulate_tokens(run_meta, prompt_tokens=3, completion_tokens=2)
    assert token_totals(run_meta) == (13, 7)


def test_token_totals_empty_when_no_usage():
    assert token_totals({}) == (None, None)


def test_combined_total_tokens():
    assert combined_total_tokens(10, 5) == 15
    assert combined_total_tokens(10, None) == 10
    assert combined_total_tokens(None, None) is None
    assert combined_total_tokens(0, 5) == 5


def test_merge_token_counts():
    assert merge_token_counts(10, 5, 50, 12) == (60, 17)
    assert merge_token_counts(None, None, 50, 12) == (50, 12)
    assert merge_token_counts(10, 5, None, None) == (10, 5)


def test_accumulate_tokens_no_op_without_run_meta():
    accumulate_tokens(None, prompt_tokens=10, completion_tokens=5)


@pytest.mark.asyncio
async def test_track_llm_usage_accumulates_without_observability():
    run_meta: dict = {}
    conf = {"run_meta": run_meta}

    await track_llm_usage(
        conf,
        run_id=uuid.uuid4(),
        purpose="planner",
        model="mock-model",
        prompt_tokens=7,
        completion_tokens=3,
    )

    assert token_totals(run_meta) == (7, 3)


@pytest.mark.asyncio
async def test_track_llm_usage_persists_and_accumulates(db_session):
    svc = ObservabilityService()
    session_id = uuid.uuid4()
    run = await svc.create_run(
        db_session,
        session_id=session_id,
        user_message_id=None,
        trace_id="trace-token",
    )
    run_meta: dict = {}
    conf = {"run_meta": run_meta, "observability": svc, "db": db_session}

    await track_llm_usage(
        conf,
        run_id=run.id,
        purpose="planner",
        model="mock-model",
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=12,
    )
    await track_llm_usage(
        conf,
        run_id=run.id,
        purpose="sub_agent:training",
        model="mock-model",
        prompt_tokens=20,
        completion_tokens=8,
        latency_ms=30,
    )

    assert token_totals(run_meta) == (30, 13)

    records = list(
        (
            await db_session.scalars(select(LlmCall).where(LlmCall.run_id == run.id))
        ).all()
    )
    assert len(records) == 2
    assert {r.purpose for r in records} == {"planner", "sub_agent:training"}
