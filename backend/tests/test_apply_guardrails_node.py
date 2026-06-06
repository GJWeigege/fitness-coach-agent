import pytest

from app.agent.coach.nodes.apply_guardrails import apply_guardrails_node
from app.agent.coach.state import initial_coach_state
from app.agent.guardrails import FALLBACK_NO_KNOWLEDGE


@pytest.mark.asyncio
async def test_apply_guardrails_uses_knowledge_search_tool_citations():
    state = initial_coach_state(
        session_id="s1",
        user_id="u1",
        user_message_id="m1",
        user_message="帮我制定一周力量训练计划",
        run_id="r1",
    )
    state["intent"] = "training"
    state["final_answer"] = "周一练深蹲，周三练卧推。"
    state["tool_calls"] = [
        {
            "name": "knowledge_search",
            "status": "ok",
            "result": {
                "citations": [
                    {
                        "chunk_id": "c1",
                        "content": "# 训练计划\n新手每周 3 次全身训练",
                        "score": 0.164,
                        "source": "hybrid",
                    }
                ]
            },
        }
    ]

    emitted: list[tuple[str, dict]] = []

    async def emit(event_type, data):
        emitted.append((event_type, data))

    result = await apply_guardrails_node(
        state,
        {"configurable": {"emit": emit}},
    )

    assert result["final_answer"] != FALLBACK_NO_KNOWLEDGE
    assert "深蹲" in result["final_answer"]
    assert len(result["rag_citations"]) == 1
    replace_events = [data for event_type, data in emitted if event_type == "replace"]
    assert not any(FALLBACK_NO_KNOWLEDGE in e.get("content", "") for e in replace_events)
