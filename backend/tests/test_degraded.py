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
def degraded_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=1,
        cot_enabled=False,
        parallel_sub_agents_enabled=True,
        max_sub_agents_per_turn=2,
        memory_max_turns=8,
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
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)
    return settings


async def _seed_turn(db_session):
    user = User(username=f"deg_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()
    user_msg = ChatMessage(session_id=session.id, role="user", content="x")
    db_session.add(user_msg)
    await db_session.flush()
    return user, session, user_msg


class ToolOnlyLLM(MockDashScopeClient):
    """Always requests tools without producing a final answer."""

    def __init__(self, planner_plan: str):
        from app.llm.dashscope_client import ToolCallComplete

        super().__init__(chat_responses=[planner_plan])
        self._tool = ToolCallComplete(id="call_1", name="knowledge_search", arguments={"query": "test"})

    async def chat_stream_with_tools(self, messages, tools, *, model=None):
        self.tool_stream_calls.append((messages, tools, {"model": model}))
        yield self._tool
        from app.llm.dashscope_client import StreamDone

        yield StreamDone(model_name="mock-model")


@pytest.mark.asyncio
async def test_degraded_react_exhausted_still_replace_passthrough(db_session, degraded_settings):
    user, session, user_msg = await _seed_turn(db_session)
    planner_plan = json.dumps(
        {
            "tasks": [{"agent": "training", "goal": "训练建议"}],
            "constraints": [],
            "estimated_tools": ["knowledge_search"],
        },
        ensure_ascii=False,
    )
    llm = ToolOnlyLLM(planner_plan)
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
        user_message="给我训练计划",
        use_rag=False,
    ):
        events.append(event)

    result = next(e for e in events if e.get("type") == "result")
    assert result["status"] in {"degraded", "completed"}
    public = [e for e in events if e.get("type") not in {"result"}]
    assert any(e.get("type") == "replace" for e in public) or result["final_answer"]
