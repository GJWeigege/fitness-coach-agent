from langchain_core.runnables import RunnableConfig

from app.agent.coach.state import CoachState
from app.agent.guardrails import CoachGuardrails


async def apply_guardrails_node(state: CoachState, config: RunnableConfig) -> dict:
    conf = config.get("configurable") or {}
    guardrails = conf.get("guardrails") or CoachGuardrails()
    knowledge_searched = any(
        tc.get("name") == "knowledge_search" for tc in (state.get("tool_calls") or [])
    )

    content, modified = guardrails.apply_guardrails(
        state.get("final_answer", ""),
        intent=state.get("intent", "unknown"),
        citations=state.get("rag_citations") or [],
        knowledge_searched=knowledge_searched,
    )

    emit = conf.get("emit")
    if modified and emit:
        await emit("replace", {"content": content})

    return {"final_answer": content}
