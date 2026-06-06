from langchain_core.runnables import RunnableConfig

from app.agent.coach.state import CoachState
from app.agent.guardrails import CoachGuardrails, collect_rag_citations


async def apply_guardrails_node(state: CoachState, config: RunnableConfig) -> dict:
    conf = config.get("configurable") or {}
    guardrails = conf.get("guardrails") or CoachGuardrails()
    tool_calls = state.get("tool_calls") or []
    knowledge_searched = any(tc.get("name") == "knowledge_search" for tc in tool_calls)
    citations = collect_rag_citations(
        rag_citations=state.get("rag_citations"),
        tool_calls=tool_calls,
    )

    content, modified = guardrails.apply_guardrails(
        state.get("final_answer", ""),
        intent=state.get("intent", "unknown"),
        citations=citations,
        knowledge_searched=knowledge_searched,
    )

    emit = conf.get("emit")
    if modified and emit:
        await emit("replace", {"content": content})

    return {"final_answer": content, "rag_citations": citations}
