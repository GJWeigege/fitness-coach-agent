from datetime import datetime, timedelta, timezone

import uuid

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import ChatMessage, ChatSession, User
from app.services.memory_service import MemoryService


class DummyLLM:
    async def chat(self, messages, model=None, tools=None, tool_choice=None):
        class Result:
            content = "用户目标增肌，已建议每周三练与蛋白质摄入。"
            prompt_tokens = 50
            completion_tokens = 12
            model_name = "qwen-plus"

        return Result()


@pytest.fixture
def memory_settings(monkeypatch):
    settings = Settings(
        memory_max_turns=3,
        memory_max_prompt_tokens=12000,
        memory_summary_trigger_turns=2,
        memory_summary_max_chars=500,
        memory_max_user_chars=8000,
        long_context_mode="summary",
        coach_answer_model="qwen-plus",
        coach_long_context_model="qwen-long",
    )
    monkeypatch.setattr("app.services.memory_service.get_settings", lambda: settings)
    return settings


async def _seed_session_with_turns(db_session, turn_count: int, *, summary: str | None = None):
    user = User(
        username=f"mem_{uuid.uuid4().hex[:8]}",
        password_hash="hash",
        password_salt="salt",
    )
    db_session.add(user)
    await db_session.flush()

    session = ChatSession(user_id=user.id, summary=summary, turn_count=turn_count)
    db_session.add(session)
    await db_session.flush()

    base_time = datetime.now(timezone.utc)
    for i in range(turn_count):
        ts = base_time + timedelta(seconds=i * 2)
        db_session.add(
            ChatMessage(
                session_id=session.id,
                role="user",
                content=f"用户问题{i + 1}",
                created_at=ts,
            )
        )
        db_session.add(
            ChatMessage(
                session_id=session.id,
                role="assistant",
                content=f"教练回答{i + 1}",
                created_at=ts + timedelta(seconds=1),
            )
        )
    await db_session.flush()
    return session


def test_estimate_tokens():
    svc = MemoryService()
    assert svc.estimate_tokens("abcd") >= 1


def test_validate_user_message_length(memory_settings):
    svc = MemoryService()
    with pytest.raises(ValueError, match="单条消息过长"):
        svc.validate_user_message_length("x" * 10000)


@pytest.mark.asyncio
async def test_sliding_window_keeps_recent_turns(db_session, memory_settings):
    session = await _seed_session_with_turns(db_session, turn_count=5)
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    user_contents = [m["content"] for m in result.messages if m["role"] == "user"]
    assert user_contents == ["用户问题3", "用户问题4", "用户问题5"]
    assert result.dropped_message_count == 2
    assert result.memory_compacted is False
    assert result.model_name is None


@pytest.mark.asyncio
async def test_session_summary_in_system_prompt(db_session, memory_settings):
    session = await _seed_session_with_turns(
        db_session, turn_count=1, summary="用户正在减脂期。"
    )
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    system_content = result.messages[0]["content"]
    assert "【会话摘要】" in system_content
    assert "用户正在减脂期。" in system_content


@pytest.mark.asyncio
async def test_token_compaction_drops_oldest(db_session, monkeypatch):
    settings = Settings(
        memory_max_turns=8,
        memory_max_prompt_tokens=20,
        memory_summary_trigger_turns=12,
        long_context_mode="summary",
    )
    monkeypatch.setattr("app.services.memory_service.get_settings", lambda: settings)

    session = await _seed_session_with_turns(db_session, turn_count=3)
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    assert result.memory_compacted is True
    assert result.dropped_message_count >= 1
    assert len([m for m in result.messages if m["role"] == "user"]) < 3


@pytest.mark.asyncio
async def test_exclude_message_id(db_session, memory_settings):
    session = await _seed_session_with_turns(db_session, turn_count=2)
    excluded_user = (
        await db_session.scalars(
            select(ChatMessage).where(
                ChatMessage.session_id == session.id,
                ChatMessage.role == "user",
                ChatMessage.content == "用户问题2",
            )
        )
    ).one()

    svc = MemoryService()
    result = await svc.build_context_messages(
        db_session, session.id, exclude_message_id=excluded_user.id
    )

    user_contents = [m["content"] for m in result.messages if m["role"] == "user"]
    assert "用户问题2" not in user_contents
    assert "用户问题1" in user_contents


@pytest.mark.asyncio
async def test_increment_turn_count(db_session, memory_settings):
    session = await _seed_session_with_turns(db_session, turn_count=0)
    session.turn_count = 1
    svc = MemoryService()
    await svc.increment_turn_count(db_session, session)
    assert session.turn_count == 2


@pytest.mark.asyncio
async def test_maybe_update_summary_below_trigger(db_session, memory_settings):
    session = await _seed_session_with_turns(db_session, turn_count=2)
    session.turn_count = 2
    svc = MemoryService()
    result = await svc.maybe_update_summary(db_session, session.id, DummyLLM())
    assert result.updated is False


@pytest.mark.asyncio
async def test_maybe_update_summary_triggers(db_session, memory_settings):
    session = await _seed_session_with_turns(db_session, turn_count=4)
    session.turn_count = 3
    svc = MemoryService()
    result = await svc.maybe_update_summary(db_session, session.id, DummyLLM())

    assert result.updated is True
    assert result.summary == "用户目标增肌，已建议每周三练与蛋白质摄入。"
    assert result.prompt_tokens == 50
    assert result.completion_tokens == 12
    assert result.model_name == "qwen-plus"
    assert result.latency_ms is not None
    await db_session.refresh(session)
    assert session.summary == result.summary
    assert session.summary_updated_at is not None
