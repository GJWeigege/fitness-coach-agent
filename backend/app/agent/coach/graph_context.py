import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.graph_service import GraphService

logger = logging.getLogger(__name__)

GRAPH_CONTEXT_HEADER = "【图谱补充】"


def format_graph_context_block(graph_context: str | None) -> str:
    if not graph_context:
        return ""
    return f"\n\n{GRAPH_CONTEXT_HEADER}\n{graph_context}"


def append_graph_to_system(system_content: str, graph_context: str | None) -> str:
    block = format_graph_context_block(graph_context)
    if not block:
        return system_content
    return system_content + block


async def resolve_graph_context_for_rag(
    db: AsyncSession,
    rag_results: list[dict],
    *,
    graph_service: GraphService | None = None,
) -> tuple[str | None, list[str]]:
    """When GRAPH_RAG_ENABLED, link RAG chunks to entities and build 1-hop context."""
    settings = get_settings()
    if not settings.graph_rag_enabled or not rag_results:
        return None, []

    service = graph_service or GraphService()
    try:
        return await service.enrich_from_rag(db, rag_results)
    except Exception:
        logger.exception("图谱上下文构建失败，将跳过 graph_context。")
        return None, []


async def build_system_with_graph_context(
    db: AsyncSession,
    base_system: str,
    rag_results: list[dict],
    *,
    graph_service: GraphService | None = None,
) -> tuple[str, list[str]]:
    """Append graph context to the system prompt when enabled."""
    graph_context, entity_names = await resolve_graph_context_for_rag(
        db,
        rag_results,
        graph_service=graph_service,
    )
    return append_graph_to_system(base_system, graph_context), entity_names
