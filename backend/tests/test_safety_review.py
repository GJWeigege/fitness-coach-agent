import pytest

from app.agent.coach.nodes.safety_review import safety_review_node
from app.agent.coach.state import initial_coach_state
from tests.coach_mocks import MockDashScopeClient


class BlockingLLM(MockDashScopeClient):
    """Always returns blocked=true from chat (safety review path)."""

    async def chat(self, messages, *, model=None, tools=None, tool_choice=None):
        from app.llm.dashscope_client import ChatResult

        return ChatResult(
            content='{"blocked": true}',
            model_name="mock",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        )


@pytest.mark.asyncio
async def test_recovery_not_blocked_when_agent_output_has_kb_safety_terms():
    state = initial_coach_state(
        session_id="s1",
        user_id="u1",
        user_message_id="m1",
        user_message="帮我制定恢复期的训练和饮食计划",
        run_id="r1",
    )
    state["intent"] = "recovery"
    state["agent_outputs"] = {
        "training": "注意禁忌动作，出现疼痛请就医评估。",
        "nutrition": "恢复期保证蛋白质摄入。",
    }

    result = await safety_review_node(state, {"configurable": {"llm": BlockingLLM()}})

    assert result["safety_blocked"] is False


@pytest.mark.asyncio
async def test_recovery_not_blocked_by_llm_even_when_llm_says_blocked():
    state = initial_coach_state(
        session_id="s1",
        user_id="u1",
        user_message_id="m1",
        user_message="帮我制定恢复期的训练和饮食计划",
        run_id="r1",
    )
    state["intent"] = "recovery"

    result = await safety_review_node(state, {"configurable": {"llm": BlockingLLM()}})

    assert result["safety_blocked"] is False


@pytest.mark.asyncio
async def test_safety_intent_blocked_on_user_red_flag_keyword():
    state = initial_coach_state(
        session_id="s1",
        user_id="u1",
        user_message_id="m1",
        user_message="训练时胸闷气短怎么办？",
        run_id="r1",
    )
    state["intent"] = "safety"

    result = await safety_review_node(state, {"configurable": {}})

    assert result["safety_blocked"] is True


@pytest.mark.asyncio
async def test_safety_intent_llm_can_block_without_keyword():
    state = initial_coach_state(
        session_id="s1",
        user_id="u1",
        user_message_id="m1",
        user_message="昨天深蹲后今天感觉不太对劲",
        run_id="r1",
    )
    state["intent"] = "safety"

    result = await safety_review_node(state, {"configurable": {"llm": BlockingLLM()}})

    assert result["safety_blocked"] is True


@pytest.mark.asyncio
async def test_safety_review_persists_step_in_db(db_session):
    from uuid import uuid4

    from sqlalchemy import select

    from app.db.models import AgentStep
    from app.services.observability_service import ObservabilityService

    obs = ObservabilityService()
    run = await obs.create_run(
        db_session,
        session_id=uuid4(),
        user_message_id=None,
        trace_id="trace-safety-step",
    )
    await db_session.commit()

    state = initial_coach_state(
        session_id=str(uuid4()),
        user_id="u1",
        user_message_id="m1",
        user_message="帮我制定恢复期的训练和饮食计划",
        run_id=str(run.id),
    )
    state["intent"] = "recovery"

    await safety_review_node(
        state,
        {
            "configurable": {
                "db": db_session,
                "observability": obs,
                "llm": BlockingLLM(),
            }
        },
    )

    steps = list(
        (
            await db_session.scalars(
                select(AgentStep).where(AgentStep.run_id == run.id).order_by(AgentStep.step_index)
            )
        ).all()
    )
    safety_steps = [step for step in steps if step.phase == "safety_review"]
    assert len(safety_steps) == 1
    assert safety_steps[0].payload["blocked"] is False
    assert safety_steps[0].payload["intent"] == "recovery"
