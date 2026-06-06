import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.db.models import AgentRun, ChatMessage, ChatSession, User
from app.services.feedback_benchmark_service import (
    FeedbackBenchmarkService,
    build_benchmark_row_from_feedback,
    build_sft_row_from_feedback,
    feedback_sample_id,
)


@pytest.mark.asyncio
async def test_sync_feedback_exports_down_to_queue_and_up_to_sft(db_session, tmp_path):
    user = User(username=f"fb_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()

    base = datetime.now(timezone.utc)
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content="如何增肌",
        created_at=base,
    )
    down_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content="不太好的回复",
        feedback="down",
        created_at=base + timedelta(seconds=1),
    )
    up_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content="很好的训练建议",
        feedback="up",
        created_at=base + timedelta(seconds=2),
    )
    db_session.add_all([user_msg, down_msg, up_msg])
    await db_session.flush()

    run = AgentRun(
        trace_id="t1",
        session_id=session.id,
        user_message_id=user_msg.id,
        intent="training",
        status="completed",
    )
    db_session.add(run)
    await db_session.flush()
    down_msg.agent_run_id = run.id
    up_msg.agent_run_id = run.id
    await db_session.flush()

    benchmark_path = tmp_path / "coach_eval.jsonl"
    sft_path = tmp_path / "coach_sft.jsonl"
    queue_path = tmp_path / "feedback_import.jsonl"
    service = FeedbackBenchmarkService(
        benchmark_path=benchmark_path,
        sft_path=sft_path,
        queue_path=queue_path,
    )

    result = await service.sync_from_feedback(db_session, dry_run=False)
    assert result.queue_added == 1
    assert result.sft_added == 1

    queue_rows = [json.loads(line) for line in queue_path.read_text(encoding="utf-8").splitlines()]
    assert queue_rows[0]["id"] == feedback_sample_id(down_msg.id)
    assert queue_rows[0]["expected_intent"] == "training"

    sft_rows = [json.loads(line) for line in sft_path.read_text(encoding="utf-8").splitlines()]
    assert sft_rows[0]["messages"][1]["content"] == "如何增肌"
    assert sft_rows[0]["message_id"] == str(up_msg.id)


@pytest.mark.asyncio
async def test_feedback_pairs_assistant_with_immediate_preceding_user(db_session, tmp_path):
    user = User(username=f"fb2_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()

    base = datetime.now(timezone.utc)
    user_turn_1 = ChatMessage(
        session_id=session.id,
        role="user",
        content="第一轮问题",
        created_at=base,
    )
    user_turn_2 = ChatMessage(
        session_id=session.id,
        role="user",
        content="第二轮问题",
        created_at=base + timedelta(seconds=10),
    )
    down_msg = ChatMessage(
        session_id=session.id,
        role="assistant",
        content="第二轮的错误回复",
        feedback="down",
        created_at=base + timedelta(seconds=11),
    )
    db_session.add_all([user_turn_1, user_turn_2, down_msg])
    await db_session.flush()

    service = FeedbackBenchmarkService(
        benchmark_path=tmp_path / "coach_eval.jsonl",
        sft_path=tmp_path / "coach_sft.jsonl",
        queue_path=tmp_path / "feedback_import.jsonl",
    )
    await service.sync_from_feedback(db_session, include_up=False, dry_run=False)

    queue_rows = [json.loads(line) for line in (tmp_path / "feedback_import.jsonl").read_text(encoding="utf-8").splitlines()]
    assert queue_rows[0]["question"] == "第二轮问题"


def test_merge_feedback_queue_into_benchmark(tmp_path):
    benchmark_path = tmp_path / "coach_eval.jsonl"
    queue_path = tmp_path / "feedback_import.jsonl"
    row = {
        "id": "fb-test-001",
        "question": "测试问题",
        "expected_intent": "training",
        "must_include_disclaimer": True,
    }
    queue_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    service = FeedbackBenchmarkService(benchmark_path=benchmark_path, queue_path=queue_path)
    result = service.merge_feedback_queue_into_benchmark()
    assert result["merged"] == 1
    merged = json.loads(benchmark_path.read_text(encoding="utf-8").strip())
    assert merged["id"] == "fb-test-001"


def test_build_rows_from_feedback():
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    user_msg = ChatMessage(session_id=session_id, role="user", content="问题")
    assistant = ChatMessage(
        session_id=session_id,
        role="assistant",
        content="回复",
        feedback="down",
        id=uuid.uuid4(),
    )
    run = AgentRun(
        id=uuid.uuid4(),
        trace_id="t",
        session_id=session_id,
        intent="nutrition",
        status="completed",
    )
    bench = build_benchmark_row_from_feedback(
        assistant=assistant,
        user_message=user_msg,
        agent_run=run,
        feedback_rating="down",
    )
    assert bench["expected_intent"] == "nutrition"
    sft = build_sft_row_from_feedback(user_message=user_msg, assistant=assistant)
    assert "messages" in sft
