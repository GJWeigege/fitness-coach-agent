import json
import uuid

import pytest

from app.agent.coach.orchestrator import CoachGraphOrchestrator
from app.core.config import Settings
from app.db.models import ChatMessage, ChatSession, User
from app.services.observability_service import ObservabilityService
from app.services.rag_service import RagService
from tests.coach_mocks import MockDashScopeClient
from tests.test_coach_graph import StubRegistry


@pytest.fixture
def step_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        agent_enable_thinking_steps=True,
        cot_enabled=False,
        graph_rag_enabled=False,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    for mod in (
        "app.agent.coach.orchestrator",
        "app.agent.coach.nodes.sub_agent",
        "app.agent.coach.nodes.plan_execute",
        "app.agent.coach.nodes.dispatch_sub_agents",
        "app.agent.coach.nodes.synthesize",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)
    return settings


async def _seed_turn(db_session):
    user = User(username=f"plan_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()
    user_msg = ChatMessage(session_id=session.id, role="user", content="placeholder")
    db_session.add(user_msg)
    await db_session.flush()
    return user, session, user_msg


@pytest.mark.asyncio
async def test_planning_step_emitted_once(db_session, step_settings):
    user, session, user_msg = await _seed_turn(db_session)
    planner_plan = json.dumps(
        {
            "tasks": [{"agent": "training", "goal": "增肌训练建议"}],
            "constraints": [],
            "estimated_tools": [],
        },
        ensure_ascii=False,
    )
    llm = MockDashScopeClient(
        chat_responses=[planner_plan],
        tool_stream_chunks=["建议渐进超负荷训练。"],
        stream_chunks=["建议渐进超负荷训练。"],
    )
    orch = CoachGraphOrchestrator(
        llm_client=llm,
        rag_service=RagService(llm_client=llm),
        observability=ObservabilityService(),
    )

    steps: list[dict] = []
    async for event in orch.stream_turn(
        db_session,
        session=session,
        user_record=user_msg,
        user_message="我想力量训练增肌",
        use_rag=False,
    ):
        if event.get("type") == "step":
            steps.append(event)

    planning = [s for s in steps if s.get("phase") == "planning"]
    assert len(planning) == 1, f"expected 1 planning step, got {len(planning)}: {planning}"
