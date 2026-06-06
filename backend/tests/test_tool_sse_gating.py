import uuid

import pytest

from app.agent.coach.nodes.sub_agent import sub_agent_node
from app.agent.coach.state import initial_coach_state
from app.agent.tools.registry import CoachToolRegistry
from app.core.config import Settings
from app.db.models import ChatSession, User
from app.llm.dashscope_client import StreamDone, ToolCallComplete
from tests.coach_mocks import MockDashScopeClient


@pytest.fixture
def tool_sse_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=4,
        cot_enabled=False,
        agent_enable_thinking_steps=False,
        cot_sse_enabled=True,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.agent.coach.nodes.sub_agent.get_settings", lambda: settings)
    return settings


class ToolEmitLLM(MockDashScopeClient):
    async def chat_stream_with_tools(self, messages, tools, *, model=None):
        yield ToolCallComplete(id="call_1", name="knowledge_search", arguments={"query": "深蹲"})
        yield "建议正文。"
        yield StreamDone(model_name="mock-model")


class StubRegistry(CoachToolRegistry):
    def __init__(self):
        pass

    def list_schemas(self, *, agent_key=None):
        return [{"type": "function", "function": {"name": "knowledge_search", "parameters": {}}}]

    async def execute(self, name, ctx, arguments):
        return {"chunks": []}


@pytest.mark.asyncio
async def test_sub_agent_suppresses_tool_sse_when_thinking_steps_disabled(
    db_session, tool_sse_settings
):
    user = User(username=f"tool_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()

    emitted: list[tuple[str, dict]] = []

    async def emit(event_type, data):
        emitted.append((event_type, data))

    state = initial_coach_state(
        session_id=str(session.id),
        user_id=str(user.id),
        user_message_id=str(uuid.uuid4()),
        user_message="深蹲技巧",
        run_id=str(uuid.uuid4()),
    )
    state["current_agent_key"] = "training"

    await sub_agent_node(
        state,
        {
            "configurable": {
                "db": db_session,
                "llm": ToolEmitLLM(),
                "tool_registry": StubRegistry(),
                "emit": emit,
            }
        },
    )

    assert not any(event_type in {"tool_call", "tool_result", "step"} for event_type, _ in emitted)
