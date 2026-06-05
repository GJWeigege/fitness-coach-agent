import uuid

from langchain_core.runnables import RunnableConfig

from app.agent.coach.graph_context import resolve_graph_context_for_rag
from app.agent.coach.state import CoachState
from app.agent.tools.base import ToolContext
from app.agent.tools.knowledge import KnowledgeSearchTool
from app.services.rag_service import RagService


async def knowledge_prefetch_node(state: CoachState, config: RunnableConfig) -> dict:
    if not state.get("use_rag", True):
        return {}

    conf = config.get("configurable") or {}
    db = conf["db"]
    rag_service = conf.get("rag_service") or RagService(conf["llm"])
    knowledge_tool = KnowledgeSearchTool(rag_service)

    tool_ctx = ToolContext(
        db=db,
        user_id=uuid.UUID(state["user_id"]),
        session_id=uuid.UUID(state["session_id"]),
        message_id=uuid.UUID(state["user_message_id"]),
        run_id=uuid.UUID(state["run_id"]),
        use_rag=True,
    )
    result = await knowledge_tool.run(tool_ctx, {"query": state.get("user_message", "")})
    citations = result.get("citations") or []
    graph_context, entity_names = await resolve_graph_context_for_rag(db, citations)

    updates: dict = {"rag_citations": citations}
    if graph_context:
        updates["graph_context"] = graph_context
    if entity_names:
        updates["graph_entities_used"] = entity_names
    return updates
