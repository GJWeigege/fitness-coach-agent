import uuid

import pytest

from app.agent.coach.orchestrator import CoachGraphOrchestrator
from app.core.config import Settings
from app.db.models import ChatMessage, ChatSession, User
from app.services.observability_service import ObservabilityService
from app.services.rag_service import RagService
from tests.coach_mocks import MockDashScopeClient


@pytest.fixture
def resilience_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=4,
        graph_rag_enabled=False,
        agent_enable_thinking_steps=False,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.agent.coach.orchestrator.get_settings", lambda: settings)
    return settings


async def _seed_turn(db_session):
    user = User(username=f"res_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()
    user_msg = ChatMessage(session_id=session.id, role="user", content="x")
    db_session.add(user_msg)
    await db_session.flush()
    return user, session, user_msg


class FailingLLM(MockDashScopeClient):
    async def chat(self, messages, *, model=None, tools=None, tool_choice=None):
        raise TimeoutError("LLM timeout")

    async def chat_stream(self, messages, *, model=None):
        raise TimeoutError("LLM timeout")
        yield  # pragma: no cover

    async def chat_stream_with_tools(self, messages, tools, *, model=None):
        raise TimeoutError("LLM timeout")
        yield  # pragma: no cover


@pytest.mark.asyncio
async def test_resilience_llm_failure_yields_error(db_session, resilience_settings):
    user, session, user_msg = await _seed_turn(db_session)
    llm = FailingLLM()
    orch = CoachGraphOrchestrator(
        llm_client=llm,
        rag_service=RagService(llm_client=llm),
        observability=ObservabilityService(),
    )

    events: list[dict] = []
    async for event in orch.stream_turn(
        db_session,
        session=session,
        user_record=user_msg,
        user_message="我想力量训练增肌",
        use_rag=False,
    ):
        events.append(event)

    assert any(e.get("type") == "error" for e in events)
    assert not any(e.get("type") == "result" for e in events)
