import json
import uuid

import pytest

from app.agent.coach.nodes.sub_agent import sub_agent_node
from app.agent.coach.state import initial_coach_state
from app.agent.tools.registry import CoachToolRegistry
from app.core.config import Settings
from app.db.models import ChatSession, User
from app.llm.dashscope_client import ToolCallComplete
from tests.coach_mocks import MockDashScopeClient


@pytest.fixture
def coach_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=4,
        cot_enabled=True,
        memory_max_turns=8,
        memory_max_prompt_tokens=12000,
        long_context_mode="summary",
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.agent.coach.nodes.sub_agent.get_settings", lambda: settings)
    return settings


async def _seed_minimal_session(db_session):
    user = User(username=f"react_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()
    return user, session


class StubRegistry(CoachToolRegistry):
    def __init__(self):
        pass

    def list_schemas(self, *, agent_key=None):
        return [
            {
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "description": "search",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                },
            }
        ]

    async def execute(self, name, ctx, arguments):
        return {"citations": [{"title": "营养指南", "score": 0.9}], "chunks": []}


@pytest.mark.asyncio
async def test_sub_agent_react_parses_cot_and_tool_then_answer(db_session, coach_settings):
    user, session = await _seed_minimal_session(db_session)
    state = initial_coach_state(
        session_id=str(session.id),
        user_id=str(user.id),
        user_message_id=str(uuid.uuid4()),
        user_message="我想增肌该怎么练？",
        run_id=str(uuid.uuid4()),
    )
    state["current_agent_key"] = "training"
    state["task_goal"] = "给出增肌训练建议"

    llm = MockDashScopeClient()
    llm.tool_stream_chunks = [
        "<reasoning>先查知识库。</reasoning>",
        ToolCallComplete(id="tc1", name="knowledge_search", arguments={"query": "增肌"}),
    ]
    llm.stream_chunks = [
        "<reasoning>结合检索结果回答。</reasoning>",
        "建议每周三练大肌群。",
    ]

    config = {
        "configurable": {
            "db": db_session,
            "llm": llm,
            "tool_registry": StubRegistry(),
            "memory_service": __import__(
                "app.services.memory_service", fromlist=["MemoryService"]
            ).MemoryService(),
        }
    }

    result = await sub_agent_node(state, config)

    assert result["agent_outputs"]["training"] == "建议每周三练大肌群。"
    assert "training" in result["cot_traces"]
    assert result["cot_traces"]["training"] == "结合检索结果回答。"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "knowledge_search"
