import json
import uuid

import pytest

from app.agent.coach.graph import build_coach_graph
from app.agent.coach.state import initial_coach_state
from app.agent.tools.registry import CoachToolRegistry
from app.core.config import Settings
from app.db.models import ChatSession, User
from app.llm.dashscope_client import ToolCallComplete
from tests.coach_mocks import MockDashScopeClient


@pytest.fixture
def graph_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=4,
        cot_enabled=True,
        parallel_sub_agents_enabled=True,
        max_sub_agents_per_turn=2,
        memory_max_turns=8,
        memory_max_prompt_tokens=12000,
        long_context_mode="summary",
        graph_rag_enabled=False,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    for mod in (
        "app.agent.coach.nodes.sub_agent",
        "app.agent.coach.nodes.plan_execute",
        "app.agent.coach.nodes.dispatch_sub_agents",
        "app.agent.coach.nodes.synthesize",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)
    return settings


async def _seed_session(db_session):
    user = User(username=f"graph_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
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
        return []

    async def execute(self, name, ctx, arguments):
        return {}


@pytest.mark.asyncio
async def test_coach_graph_compiles_and_reaches_end_for_training(db_session, graph_settings):
    user, session = await _seed_session(db_session)
    run_id = str(uuid.uuid4())
    state = initial_coach_state(
        session_id=str(session.id),
        user_id=str(user.id),
        user_message_id=str(uuid.uuid4()),
        user_message="我想力量训练增肌",
        run_id=run_id,
    )

    planner_plan = json.dumps(
        {
            "tasks": [{"agent": "training", "goal": "增肌训练建议"}],
            "constraints": ["引用知识库"],
            "estimated_tools": ["knowledge_search"],
        },
        ensure_ascii=False,
    )
    llm = MockDashScopeClient(
        chat_responses=[planner_plan],
        tool_stream_chunks=["建议渐进超负荷训练。"],
        stream_chunks=["建议渐进超负荷训练。"],
    )

    emitted: list[tuple[str, dict]] = []

    async def emit(event_type, data):
        emitted.append((event_type, data))

    graph = build_coach_graph()
    config = {
        "configurable": {
            "db": db_session,
            "llm": llm,
            "tool_registry": StubRegistry(),
            "emit": emit,
            "run_meta": {"parallel_agents_used": False},
        }
    }

    result = await graph.ainvoke(state, config)

    assert result.get("final_answer")
    assert result.get("intent") == "training"
    assert "training" in result.get("agent_outputs", {})
    replace_events = [e for e in emitted if e[0] == "replace"]
    delta_events = [e for e in emitted if e[0] == "delta"]
    assert len(delta_events) == 0
    assert len(replace_events) >= 1


@pytest.mark.asyncio
async def test_coach_graph_chitchat_passthrough_replace(db_session, graph_settings):
    user, session = await _seed_session(db_session)
    state = initial_coach_state(
        session_id=str(session.id),
        user_id=str(user.id),
        user_message_id=str(uuid.uuid4()),
        user_message="你好",
        run_id=str(uuid.uuid4()),
    )

    llm = MockDashScopeClient(stream_chunks=["你好，很高兴为你服务！"])
    emitted: list[tuple[str, dict]] = []

    async def emit(event_type, data):
        emitted.append((event_type, data))

    graph = build_coach_graph()
    result = await graph.ainvoke(
        state,
        {
            "configurable": {
                "db": db_session,
                "llm": llm,
                "tool_registry": StubRegistry(),
                "emit": emit,
                "run_meta": {},
            }
        },
    )

    assert result.get("intent") == "chitchat"
    assert result.get("final_answer") == "你好，很高兴为你服务！"
    assert [e[0] for e in emitted] == ["replace"]
