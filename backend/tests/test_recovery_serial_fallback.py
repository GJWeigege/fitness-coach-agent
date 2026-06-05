import json
import uuid

import pytest

from app.agent.coach.graph import build_coach_graph
from app.agent.coach.state import initial_coach_state
from app.agent.tools.registry import CoachToolRegistry
from app.core.config import Settings
from app.db.models import ChatSession, User
from tests.coach_mocks import MockDashScopeClient


@pytest.fixture
def serial_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=4,
        cot_enabled=False,
        parallel_sub_agents_enabled=False,
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


class StubRegistry(CoachToolRegistry):
    def __init__(self):
        pass

    def list_schemas(self, *, agent_key=None):
        return []

    async def execute(self, name, ctx, arguments):
        return {}


class SerialRecoveryLLM(MockDashScopeClient):
    def __init__(self, planner_plan: str):
        super().__init__(chat_responses=[planner_plan])
        self._agent_index = 0
        self.agent_answers = ["训练恢复方案", "营养恢复方案"]
        self.merge_chunks = ["合并", "建议"]

    async def chat_stream_with_tools(self, messages, tools, *, model=None):
        answer = self.agent_answers[min(self._agent_index, len(self.agent_answers) - 1)]
        self._agent_index += 1
        yield answer

    async def chat_stream(self, messages, *, model=None):
        for chunk in self.merge_chunks:
            yield chunk
        from app.llm.dashscope_client import StreamDone

        yield StreamDone(model_name="mock-model")


@pytest.mark.asyncio
async def test_recovery_serial_fallback_when_parallel_disabled(db_session, serial_settings):
    user = User(username=f"ser_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()

    run_meta = {"parallel_agents_used": False}
    planner_plan = json.dumps(
        {
            "tasks": [
                {"agent": "training", "goal": "恢复训练", "parallel_group": 0},
                {"agent": "nutrition", "goal": "恢复饮食", "parallel_group": 0},
            ],
            "constraints": [],
            "estimated_tools": ["knowledge_search"],
        },
        ensure_ascii=False,
    )
    llm = SerialRecoveryLLM(planner_plan)
    emitted: list[tuple[str, dict]] = []

    async def emit(event_type, data):
        emitted.append((event_type, data))

    state = initial_coach_state(
        session_id=str(session.id),
        user_id=str(user.id),
        user_message_id=str(uuid.uuid4()),
        user_message="恢复期训练和饮食怎么安排",
        run_id=str(uuid.uuid4()),
    )

    graph = build_coach_graph()
    result = await graph.ainvoke(
        state,
        {
            "configurable": {
                "db": db_session,
                "llm": llm,
                "tool_registry": StubRegistry(),
                "emit": emit,
                "run_meta": run_meta,
            }
        },
    )

    assert "training" in result.get("agent_outputs", {})
    assert "nutrition" in result.get("agent_outputs", {})
    assert run_meta["parallel_agents_used"] is False
    assert llm._agent_index == 2
    assert any(e[0] == "delta" for e in emitted)
