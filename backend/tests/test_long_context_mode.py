import uuid

import pytest

from app.core.config import Settings
from app.db.models import ChatMessage, ChatSession, User
from app.services.memory_service import MemoryService


@pytest.fixture
def full_context_settings(monkeypatch):
    settings = Settings(
        memory_max_turns=3,
        memory_max_prompt_tokens=50,
        long_context_mode="full",
        coach_long_context_model="qwen-long",
        coach_answer_model="qwen-plus",
    )
    monkeypatch.setattr("app.services.memory_service.get_settings", lambda: settings)
    return settings


@pytest.fixture
def summary_context_settings(monkeypatch):
    settings = Settings(
        memory_max_turns=3,
        memory_max_prompt_tokens=50,
        long_context_mode="summary",
        coach_long_context_model="qwen-long",
        coach_answer_model="qwen-plus",
    )
    monkeypatch.setattr("app.services.memory_service.get_settings", lambda: settings)
    return settings


async def _seed_session(db_session, turn_count: int, *, summary: str | None = None):
    user = User(
        username=f"ctx_{uuid.uuid4().hex[:8]}",
        password_hash="hash",
        password_salt="salt",
    )
    db_session.add(user)
    await db_session.flush()

    session = ChatSession(user_id=user.id, summary=summary)
    db_session.add(session)
    await db_session.flush()

    for i in range(turn_count):
        db_session.add(
            ChatMessage(
                session_id=session.id,
                role="user",
                content=f"turn-{i + 1}-user-" + ("x" * 40),
            )
        )
        db_session.add(
            ChatMessage(
                session_id=session.id,
                role="assistant",
                content=f"turn-{i + 1}-assistant-" + ("y" * 40),
            )
        )
    await db_session.flush()
    return session


@pytest.mark.asyncio
async def test_full_mode_includes_all_history(db_session, full_context_settings):
    session = await _seed_session(db_session, turn_count=6)
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    user_contents = [m["content"] for m in result.messages if m["role"] == "user"]
    assert len(user_contents) == 6
    assert user_contents[0].startswith("turn-1-user")
    assert user_contents[-1].startswith("turn-6-user")
    assert result.dropped_message_count == 0
    assert result.memory_compacted is False


@pytest.mark.asyncio
async def test_full_mode_uses_long_context_model(db_session, full_context_settings):
    session = await _seed_session(db_session, turn_count=2)
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    assert result.model_name == "qwen-long"


@pytest.mark.asyncio
async def test_summary_mode_does_not_set_long_context_model(db_session, summary_context_settings):
    session = await _seed_session(db_session, turn_count=2)
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    assert result.model_name is None


@pytest.mark.asyncio
async def test_full_mode_keeps_summary_anchor(db_session, full_context_settings):
    session = await _seed_session(db_session, turn_count=2, summary="长期跑步膝伤史。")
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    system_content = result.messages[0]["content"]
    assert "【会话摘要】" in system_content
    assert "长期跑步膝伤史。" in system_content


@pytest.mark.asyncio
async def test_full_mode_skips_token_budget_compaction(db_session, full_context_settings):
    session = await _seed_session(db_session, turn_count=6)
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    assert svc.estimate_messages_tokens(result.messages) > full_context_settings.memory_max_prompt_tokens
    assert result.memory_compacted is False
    assert len([m for m in result.messages if m["role"] == "user"]) == 6


@pytest.mark.asyncio
async def test_summary_mode_applies_window_and_compaction(db_session, summary_context_settings):
    session = await _seed_session(db_session, turn_count=6)
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    user_contents = [m["content"] for m in result.messages if m["role"] == "user"]
    assert len(user_contents) <= 3
    assert result.dropped_message_count >= 3
    assert result.model_name is None


@pytest.mark.asyncio
async def test_full_mode_case_insensitive(db_session, monkeypatch):
    settings = Settings(
        memory_max_turns=2,
        memory_max_prompt_tokens=50,
        long_context_mode="FULL",
        coach_long_context_model="qwen-long",
    )
    monkeypatch.setattr("app.services.memory_service.get_settings", lambda: settings)

    session = await _seed_session(db_session, turn_count=4)
    svc = MemoryService()
    result = await svc.build_context_messages(db_session, session.id)

    assert result.model_name == "qwen-long"
    assert len([m for m in result.messages if m["role"] == "user"]) == 4
