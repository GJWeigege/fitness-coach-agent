import json
import uuid

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import AgentRun, ChatMessage, ChatSession, LlmCall, User
from app.services.chat_service import ChatService
from app.services.rag_service import RagService
from tests.coach_mocks import MockDashScopeClient


@pytest.fixture
def chat_stream_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=4,
        cot_enabled=False,
        parallel_sub_agents_enabled=True,
        max_sub_agents_per_turn=2,
        memory_max_turns=8,
        memory_max_prompt_tokens=12000,
        long_context_mode="summary",
        graph_rag_enabled=False,
        agent_enable_thinking_steps=False,
        memory_summary_trigger_turns=999,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    for mod in (
        "app.services.chat_service",
        "app.agent.coach.orchestrator",
        "app.agent.coach.nodes.sub_agent",
        "app.agent.coach.nodes.plan_execute",
        "app.agent.coach.nodes.dispatch_sub_agents",
        "app.agent.coach.nodes.synthesize",
        "app.agent.tools.registry",
        "app.services.memory_service",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)
    return settings


async def _new_session(db_session):
    user = User(username=f"chat_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()
    return user, session


def _chat_service(llm: MockDashScopeClient) -> ChatService:
    rag = RagService(llm_client=llm)
    return ChatService(llm_client=llm, rag_service=rag)


@pytest.mark.asyncio
async def test_chat_stream_done_after_assistant_persisted(db_session, chat_stream_settings):
    user, session = await _new_session(db_session)
    planner_plan = json.dumps(
        {
            "tasks": [{"agent": "training", "goal": "增肌"}],
            "constraints": [],
            "estimated_tools": [],
        },
        ensure_ascii=False,
    )
    llm = MockDashScopeClient(
        chat_responses=[planner_plan],
        tool_stream_chunks=["训练建议正文。"],
        stream_chunks=["训练建议正文。"],
    )
    service = _chat_service(llm)

    events: list[dict] = []
    async for event in service.stream_message(
        db_session,
        user_message="我想力量训练增肌",
        user_id=user.id,
        session_id=session.id,
        use_rag=False,
    ):
        events.append(event)

    assert events[-1]["type"] == "done"
    assert "result" not in [e.get("type") for e in events]

    assistants = list(
        (
            await db_session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id, ChatMessage.role == "assistant")
            )
        ).all()
    )
    assert len(assistants) == 1
    assert assistants[0].content
    assert assistants[0].agent_run_id is not None
    assert assistants[0].prompt_tokens == 20
    assert assistants[0].completion_tokens == 10
    assert assistants[0].total_tokens == 30

    agent_run = await db_session.get(AgentRun, assistants[0].agent_run_id)
    assert agent_run is not None
    assert agent_run.prompt_tokens == 20
    assert agent_run.completion_tokens == 10

    llm_calls = list(
        (
            await db_session.scalars(
                select(LlmCall).where(LlmCall.run_id == agent_run.id)
            )
        ).all()
    )
    assert len(llm_calls) >= 2
    assert sum(c.prompt_tokens or 0 for c in llm_calls) == 20
    assert sum(c.completion_tokens or 0 for c in llm_calls) == 10

    planner_call = next(c for c in llm_calls if c.purpose == "planner")
    assert planner_call.step_id is not None


@pytest.mark.asyncio
async def test_chat_stream_single_agent_no_delta(db_session, chat_stream_settings):
    user, session = await _new_session(db_session)
    planner_plan = json.dumps(
        {
            "tasks": [{"agent": "training", "goal": "增肌"}],
            "constraints": [],
            "estimated_tools": [],
        },
        ensure_ascii=False,
    )
    llm = MockDashScopeClient(
        chat_responses=[planner_plan],
        tool_stream_chunks=["无流式增量。"],
        stream_chunks=["无流式增量。"],
    )
    service = _chat_service(llm)

    public_types: list[str] = []
    async for event in service.stream_message(
        db_session,
        user_message="力量训练",
        user_id=user.id,
        session_id=session.id,
        use_rag=False,
    ):
        if event.get("type") not in {"result"}:
            public_types.append(event["type"])

    assert "delta" not in public_types
    assert "replace" in public_types
    assert public_types[-1] == "done"


@pytest.mark.asyncio
async def test_chat_stream_persists_agent_steps(db_session, monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=4,
        cot_enabled=False,
        parallel_sub_agents_enabled=True,
        max_sub_agents_per_turn=2,
        memory_max_turns=8,
        memory_max_prompt_tokens=12000,
        long_context_mode="summary",
        graph_rag_enabled=False,
        agent_enable_thinking_steps=True,
        memory_summary_trigger_turns=999,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    for mod in (
        "app.services.chat_service",
        "app.agent.coach.orchestrator",
        "app.agent.coach.nodes.sub_agent",
        "app.agent.coach.nodes.plan_execute",
        "app.agent.coach.nodes.dispatch_sub_agents",
        "app.agent.coach.nodes.synthesize",
        "app.agent.tools.registry",
        "app.services.memory_service",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)

    user, session = await _new_session(db_session)
    planner_plan = json.dumps(
        {
            "tasks": [{"agent": "training", "goal": "增肌"}],
            "constraints": [],
            "estimated_tools": [],
        },
        ensure_ascii=False,
    )
    llm = MockDashScopeClient(
        chat_responses=[planner_plan],
        tool_stream_chunks=["训练建议正文。"],
        stream_chunks=["训练建议正文。"],
    )
    service = _chat_service(llm)

    async for _event in service.stream_message(
        db_session,
        user_message="我想力量训练增肌",
        user_id=user.id,
        session_id=session.id,
        use_rag=False,
    ):
        pass

    assistants = list(
        (
            await db_session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session.id, ChatMessage.role == "assistant")
            )
        ).all()
    )
    assert len(assistants) == 1
    assert assistants[0].agent_steps is not None
    persisted = assistants[0].agent_steps["items"]
    assert isinstance(persisted, list)
    assert len(persisted) >= 1
    assert any(step.get("phase") == "memory_summary" for step in persisted)
