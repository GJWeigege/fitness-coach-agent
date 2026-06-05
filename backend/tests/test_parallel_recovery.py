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
def parallel_settings(monkeypatch):
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


async def _seed_session(db_session):
    user = User(username=f"par_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()
    return user, session


class MultiSubAgentLLM(MockDashScopeClient):
    def __init__(self, planner_plan: str, agent_answers: dict[str, str], merge_chunks: list[str]):
        super().__init__(chat_responses=[planner_plan])
        self.agent_answers = agent_answers
        self.merge_chunks = merge_chunks
        self._agent_calls = 0

    async def chat_stream_with_tools(self, messages, tools, *, model=None):
        self.tool_stream_calls.append((messages, tools, {"model": model}))
        agent_key = "training"
        for suffix, key in (("训练教练", "training"), ("营养教练", "nutrition"), ("安全教练", "safety")):
            if suffix in "".join(m.get("content", "") or "" for m in messages):
                agent_key = key
                break
        answer = self.agent_answers.get(agent_key, "默认建议")
        yield answer

    async def chat_stream(self, messages, *, model=None):
        self.stream_calls.append((messages, {"model": model}))
        for chunk in self.merge_chunks:
            yield chunk
        from app.llm.dashscope_client import StreamDone

        yield StreamDone(model_name="mock-model")


@pytest.mark.asyncio
async def test_parallel_recovery_populates_both_agents_and_uses_delta(db_session, parallel_settings):
    user, session = await _seed_session(db_session)
    run_meta = {"parallel_agents_used": False}
    planner_plan = json.dumps(
        {
            "tasks": [
                {"agent": "training", "goal": "恢复训练", "parallel_group": 0},
                {"agent": "nutrition", "goal": "恢复饮食", "parallel_group": 0},
            ],
            "constraints": ["低冲击"],
            "estimated_tools": ["knowledge_search"],
        },
        ensure_ascii=False,
    )
    llm = MultiSubAgentLLM(
        planner_plan,
        {"training": "低冲击训练方案", "nutrition": "高蛋白抗炎饮食"},
        ["综合恢复建议：", "训练与营养并重。"],
    )

    emitted: list[tuple[str, dict]] = []

    async def emit(event_type, data):
        emitted.append((event_type, data))

    state = initial_coach_state(
        session_id=str(session.id),
        user_id=str(user.id),
        user_message_id=str(uuid.uuid4()),
        user_message="帮我制定恢复期的训练和饮食计划",
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

    assert result.get("intent") == "recovery"
    assert "training" in result.get("agent_outputs", {})
    assert "nutrition" in result.get("agent_outputs", {})
    assert run_meta["parallel_agents_used"] is True
    delta_events = [e for e in emitted if e[0] == "delta"]
    replace_events = [e for e in emitted if e[0] == "replace"]
    assert len(delta_events) >= 1
    first_delta_idx = next(i for i, e in enumerate(emitted) if e[0] == "delta")
    if replace_events:
        first_replace_idx = next(i for i, e in enumerate(emitted) if e[0] == "replace")
        assert first_delta_idx < first_replace_idx
    assert "综合恢复建议" in result.get("final_answer", "")
