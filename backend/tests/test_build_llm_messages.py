import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.agent.coach.nodes.build_llm_messages import build_llm_messages
from app.agent.coach.state import initial_coach_state
from app.core.config import Settings
from app.db.models import ChatMessage, ChatSession, User
from app.services.memory_service import MemoryService
from tests.coach_mocks import MockDashScopeClient


@pytest.fixture
def memory_settings(monkeypatch):
    settings = Settings(
        memory_max_turns=8,
        memory_max_prompt_tokens=12000,
        memory_summary_trigger_turns=12,
        memory_max_user_chars=8000,
        long_context_mode="summary",
        coach_answer_model="qwen-plus",
        coach_long_context_model="qwen-long",
    )
    monkeypatch.setattr("app.services.memory_service.get_settings", lambda: settings)
    return settings


async def _seed_session_with_turns(db_session, turn_count: int):
    user = User(
        username=f"coach_{uuid.uuid4().hex[:8]}",
        password_hash="hash",
        password_salt="salt",
    )
    db_session.add(user)
    await db_session.flush()

    session = ChatSession(user_id=user.id, turn_count=turn_count)
    db_session.add(session)
    await db_session.flush()

    base_time = datetime.now(timezone.utc)
    for i in range(turn_count):
        ts = base_time + timedelta(seconds=i * 2)
        db_session.add(
            ChatMessage(
                session_id=session.id,
                role="user",
                content=f"历史用户问题{i + 1}",
                created_at=ts,
            )
        )
        db_session.add(
            ChatMessage(
                session_id=session.id,
                role="assistant",
                content=f"历史教练回答{i + 1}",
                created_at=ts + timedelta(seconds=1),
            )
        )
    await db_session.flush()
    return user, session


@pytest.mark.asyncio
async def test_build_llm_messages_includes_three_turn_history(db_session, memory_settings):
    user, session = await _seed_session_with_turns(db_session, 3)
    current_message_id = uuid.uuid4()
    state = initial_coach_state(
        session_id=str(session.id),
        user_id=str(user.id),
        user_message_id=str(current_message_id),
        user_message="本轮新问题",
        run_id=str(uuid.uuid4()),
    )
    state["user_profile"] = {"goals": "增肌", "experience_level": "intermediate"}

    config = {
        "configurable": {
            "db": db_session,
            "llm": MockDashScopeClient(),
            "memory_service": MemoryService(),
        }
    }

    messages, memory_result = await build_llm_messages(state, config, agent_key="training")

    user_contents = [m["content"] for m in messages if m["role"] == "user"]
    assert "历史用户问题1" in user_contents
    assert "历史用户问题2" in user_contents
    assert "历史用户问题3" in user_contents
    assert "本轮新问题" in user_contents
    assert memory_result.dropped_message_count == 0
    assert any("增肌" in m["content"] for m in messages if m["role"] == "system")
