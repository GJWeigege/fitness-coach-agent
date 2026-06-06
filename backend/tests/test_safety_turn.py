import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.agent.guardrails import COACH_DISCLAIMER, CoachGuardrails
from app.agent.coach.nodes.safety_review import SAFETY_BLOCKED_TEMPLATE
from app.core.config import Settings
from app.db.models import AgentRun, ChatMessage, ChatSession, User
from app.services.chat_service import ChatService
from app.services.rag_service import RagService
from tests.coach_mocks import MockDashScopeClient


@pytest.fixture
def safety_stream_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=4,
        cot_enabled=False,
        parallel_sub_agents_enabled=False,
        max_sub_agents_per_turn=1,
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
        "app.agent.coach.nodes.safety_review",
        "app.agent.tools.registry",
        "app.services.memory_service",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)
    return settings


@pytest.mark.asyncio
async def test_safety_turn_blocked_template_replace_only(db_session, safety_stream_settings):
    user = User(username=f"safety_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()

    planner_plan = json.dumps(
        {
            "tasks": [{"agent": "safety", "goal": "评估胸闷风险"}],
            "constraints": [],
            "estimated_tools": ["check_contraindication"],
        },
        ensure_ascii=False,
    )
    llm = MockDashScopeClient(
        chat_responses=[planner_plan],
        tool_stream_chunks=["请先停止训练并观察症状。"],
        stream_chunks=["请先停止训练并观察症状。"],
    )
    service = ChatService(llm_client=llm, rag_service=RagService(llm_client=llm))

    events: list[dict] = []
    async for event in service.stream_message(
        db_session,
        user_message="训练时胸闷气短怎么办？",
        user_id=user.id,
        session_id=session.id,
        use_rag=False,
    ):
        events.append(event)

    public = [e for e in events if e.get("type") not in {"result"}]
    assert "delta" not in [e.get("type") for e in public]
    replace_events = [e for e in public if e.get("type") == "replace"]
    assert len(replace_events) >= 1
    assert SAFETY_BLOCKED_TEMPLATE[:20] in replace_events[-1].get("content", "")
    assert COACH_DISCLAIMER in replace_events[-1].get("content", "")
    assert public[-1]["type"] == "done"

    assistant = await db_session.scalar(
        select(ChatMessage).where(
            ChatMessage.session_id == session.id,
            ChatMessage.role == "assistant",
        )
    )
    assert assistant is not None
    assert COACH_DISCLAIMER in assistant.content
    assert not CoachGuardrails().contains_banned_diagnosis(assistant.content)

    run = await db_session.get(AgentRun, assistant.agent_run_id)
    assert run is not None
    assert run.intent == "safety"
