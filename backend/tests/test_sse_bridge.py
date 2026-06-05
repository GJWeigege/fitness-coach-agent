import json
import uuid

import pytest

from app.agent.coach.orchestrator import CoachGraphOrchestrator
from app.core.config import Settings
from app.db.models import ChatMessage, ChatSession, User
from app.services.observability_service import ObservabilityService
from app.services.rag_service import RagService
from tests.coach_mocks import MockDashScopeClient
from tests.test_parallel_recovery import MultiSubAgentLLM, StubRegistry


@pytest.fixture
def bridge_settings(monkeypatch):
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
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    for mod in (
        "app.agent.coach.orchestrator",
        "app.agent.coach.nodes.sub_agent",
        "app.agent.coach.nodes.plan_execute",
        "app.agent.coach.nodes.dispatch_sub_agents",
        "app.agent.coach.nodes.synthesize",
        "app.agent.tools.registry",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)
    return settings


async def _seed_turn(db_session):
    user = User(username=f"sse_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()
    user_msg = ChatMessage(session_id=session.id, role="user", content="placeholder")
    db_session.add(user_msg)
    await db_session.flush()
    return user, session, user_msg


def _orchestrator(llm) -> CoachGraphOrchestrator:
    rag = RagService(llm_client=llm)
    return CoachGraphOrchestrator(llm_client=llm, rag_service=rag, observability=ObservabilityService())


@pytest.mark.asyncio
async def test_sse_bridge_single_agent_replace_only(db_session, bridge_settings):
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
        tool_stream_chunks=["渐进超负荷训练建议。"],
        stream_chunks=["渐进超负荷训练建议。"],
    )
    orch = _orchestrator(llm)

    events: list[dict] = []
    async for event in orch.stream_turn(
        db_session,
        session=session,
        user_record=user_msg,
        user_message="我想力量训练增肌",
        use_rag=False,
    ):
        events.append(event)

    public = [e for e in events if e.get("type") != "result"]
    types = [e["type"] for e in public]
    assert "delta" not in types
    assert "replace" in types
    assert types[-1] in {"session", "replace"}
    assert any(e.get("type") == "done" for e in events) is False
    result = next(e for e in events if e.get("type") == "result")
    assert result["final_answer"]


@pytest.mark.asyncio
async def test_sse_bridge_recovery_delta_before_result(db_session, bridge_settings):
    user, session, user_msg = await _seed_turn(db_session)
    planner_plan = json.dumps(
        {
            "tasks": [
                {"agent": "training", "goal": "恢复训练", "parallel_group": 0},
                {"agent": "nutrition", "goal": "恢复饮食", "parallel_group": 0},
            ],
            "constraints": ["低冲击"],
            "estimated_tools": [],
        },
        ensure_ascii=False,
    )
    llm = MultiSubAgentLLM(
        planner_plan,
        {"training": "低冲击训练", "nutrition": "高蛋白饮食"},
        ["综合恢复：", "训练与营养。"],
    )
    orch = _orchestrator(llm)

    events: list[dict] = []
    async for event in orch.stream_turn(
        db_session,
        session=session,
        user_record=user_msg,
        user_message="帮我制定恢复期的训练和饮食计划",
        use_rag=False,
    ):
        events.append(event)

    public_types = [e["type"] for e in events if e.get("type") not in {"result"}]
    assert "delta" in public_types
    first_delta = next(i for i, t in enumerate(public_types) if t == "delta")
    synthesize_idx = next(
        (i for i, e in enumerate(events) if e.get("type") == "step" and e.get("phase") == "synthesizing"),
        None,
    )
    if synthesize_idx is not None:
        assert first_delta > synthesize_idx or "delta" in [events[i]["type"] for i in range(synthesize_idx, len(events))]
    result = next(e for e in events if e.get("type") == "result")
    assert "综合恢复" in result["final_answer"]
