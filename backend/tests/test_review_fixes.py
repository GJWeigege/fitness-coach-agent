import json
import uuid

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import AgentStep, ChatMessage, ChatSession, User
from app.services.chat_service import ChatService
from app.services.rag_service import RagService
from tests.coach_mocks import MockDashScopeClient


@pytest.fixture
def memory_step_settings(monkeypatch):
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
        memory_summary_trigger_turns=1,
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


@pytest.mark.asyncio
async def test_memory_summary_step_after_assistant_persisted(db_session, memory_step_settings):
    user = User(username=f"mem_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()

    planner_plan = json.dumps(
        {
            "tasks": [{"agent": "training", "goal": "增肌"}],
            "constraints": [],
            "estimated_tools": [],
        },
        ensure_ascii=False,
    )
    llm = MockDashScopeClient(
        chat_responses=[planner_plan, "会话摘要内容"],
        tool_stream_chunks=["训练建议正文。"],
        stream_chunks=["训练建议正文。"],
    )
    rag = RagService(llm_client=llm)
    service = ChatService(llm_client=llm, rag_service=rag)

    events: list[dict] = []
    async for event in service.stream_message(
        db_session,
        user_message="我想增肌",
        user_id=user.id,
        session_id=session.id,
        use_rag=False,
    ):
        events.append(event)

    public = [e for e in events if e.get("type") != "result"]
    done_idx = next(i for i, e in enumerate(public) if e["type"] == "done")
    memory_idx = next(i for i, e in enumerate(public) if e.get("phase") == "memory_summary")
    assert memory_idx < done_idx

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


@pytest.mark.asyncio
async def test_finalize_run_redacts_cot_in_step_payload(db_session, memory_step_settings):
    from app.agent.coach.orchestrator import CoachGraphOrchestrator, CoachRunResult

    user = User(username=f"cot_{uuid.uuid4().hex[:8]}", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()
    session = ChatSession(user_id=user.id)
    db_session.add(session)
    await db_session.flush()

    user_msg = ChatMessage(session_id=session.id, role="user", content="问题")
    assistant = ChatMessage(session_id=session.id, role="assistant", content="建议")
    db_session.add(user_msg)
    db_session.add(assistant)
    await db_session.flush()

    from app.services.observability_service import ObservabilityService

    obs = ObservabilityService()
    run = await obs.create_run(
        db_session,
        session_id=session.id,
        user_message_id=user_msg.id,
        trace_id="trace-1",
    )
    run_id = run.id
    result = CoachRunResult(
        run_id=run_id,
        trace_id="trace-1",
        final_answer="建议",
        citations=[],
        intent="training",
        execution_plan=None,
        cot_traces={"training": "用户可能有骨折了的情况"},
        tool_calls=[],
        graph_entities_used=[],
        model_name="mock",
        prompt_tokens=None,
        completion_tokens=None,
        status="completed",
        memory_compacted=False,
        dropped_message_count=0,
        total_latency_ms=10,
        parallel_agents_used=False,
    )

    orchestrator = CoachGraphOrchestrator(
        llm_client=MockDashScopeClient(),
        rag_service=RagService(llm_client=MockDashScopeClient()),
    )

    await orchestrator.finalize_run(
        db_session,
        run_id=run_id,
        assistant_message_id=assistant.id,
        memory_summary_updated=False,
        result=result,
    )
    await db_session.commit()

    steps = list(
        (
            await db_session.scalars(
                select(AgentStep).where(AgentStep.run_id == run_id).order_by(AgentStep.step_index)
            )
        ).all()
    )
    cot_payload = steps[-1].payload.get("cot", {})
    assert "骨折了" not in json.dumps(cot_payload, ensure_ascii=False)
    assert "【已省略】" in json.dumps(cot_payload, ensure_ascii=False)
