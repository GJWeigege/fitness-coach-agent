import logging
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import GraphEdge, GraphEntity, GraphEntityLink, KnowledgeChunk

logger = logging.getLogger(__name__)

LINK_CONFIDENCE_THRESHOLD = 0.45
ENTITY_MATCH_TOP_K = 2


class EmbeddingClient(Protocol):
    async def embedding(self, texts: list[str]) -> list[list[float]]: ...


class GraphService:
    def __init__(self, llm_client: EmbeddingClient | None = None) -> None:
        self.settings = get_settings()
        self.llm_client = llm_client

    def _entity_label(self, entity: GraphEntity) -> str:
        return f"{entity.entity_type}:{entity.name}"

    async def _match_entities_for_chunk(
        self,
        db: AsyncSession,
        *,
        chunk_id: uuid.UUID,
        chunk_vector: list[float],
    ) -> list[tuple[GraphEntity, float]]:
        distance_expr = GraphEntity.embedding.cosine_distance(chunk_vector)
        stmt = (
            select(GraphEntity, distance_expr.label("distance"))
            .order_by(distance_expr)
            .limit(ENTITY_MATCH_TOP_K)
        )
        rows = (await db.execute(stmt)).all()
        matches: list[tuple[GraphEntity, float]] = []
        for entity, distance in rows:
            confidence = round(1 - float(distance), 6)
            if confidence >= LINK_CONFIDENCE_THRESHOLD:
                matches.append((entity, confidence))
        if not matches:
            return []

        existing = set(
            (
                await db.scalars(
                    select(GraphEntityLink.entity_id).where(GraphEntityLink.chunk_id == chunk_id)
                )
            ).all()
        )
        for entity, confidence in matches:
            if entity.id in existing:
                continue
            db.add(
                GraphEntityLink(
                    chunk_id=chunk_id,
                    entity_id=entity.id,
                    confidence=confidence,
                )
            )
        await db.flush()
        return matches

    async def link_entities(
        self,
        db: AsyncSession,
        rag_results: list[dict],
    ) -> tuple[list[uuid.UUID], list[str]]:
        """Link graph entities to RAG chunks via embedding similarity."""
        if not rag_results:
            return [], []

        chunk_ids: list[uuid.UUID] = []
        for item in rag_results:
            raw_id = item.get("chunk_id")
            if not raw_id:
                continue
            try:
                chunk_ids.append(uuid.UUID(str(raw_id)))
            except ValueError:
                logger.warning("跳过无效 chunk_id: %s", raw_id)

        if not chunk_ids:
            return [], []

        chunks = {
            row.id: row
            for row in (
                await db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids)))
            ).all()
        }

        linked_entity_ids: list[uuid.UUID] = []
        linked_entity_names: list[str] = []
        seen_ids: set[uuid.UUID] = set()

        for chunk_id in chunk_ids:
            chunk = chunks.get(chunk_id)
            if chunk is None:
                continue
            matches = await self._match_entities_for_chunk(
                db,
                chunk_id=chunk_id,
                chunk_vector=list(chunk.embedding),
            )
            for entity, _ in matches:
                if entity.id in seen_ids:
                    continue
                seen_ids.add(entity.id)
                linked_entity_ids.append(entity.id)
                linked_entity_names.append(entity.name)

        return linked_entity_ids, linked_entity_names

    async def build_one_hop_context(
        self,
        db: AsyncSession,
        entity_ids: list[uuid.UUID],
    ) -> str | None:
        """Build a readable 1-hop neighborhood context string for linked entities."""
        if not entity_ids:
            return None

        entities = {
            row.id: row
            for row in (
                await db.scalars(select(GraphEntity).where(GraphEntity.id.in_(entity_ids)))
            ).all()
        }
        if not entities:
            return None

        stmt = select(GraphEdge).where(
            GraphEdge.source_id.in_(entity_ids) | GraphEdge.target_id.in_(entity_ids)
        )
        edges = (await db.scalars(stmt)).all()
        if not edges:
            seed_lines = [f"- {entity.name} ({entity.entity_type})" for entity in entities.values()]
            return "图谱关联（1-hop）:\n" + "\n".join(seed_lines)

        neighbor_ids = {
            edge.target_id if edge.source_id in entities else edge.source_id for edge in edges
        } - set(entity_ids)
        neighbor_map = {}
        if neighbor_ids:
            neighbor_map = {
                row.id: row
                for row in (
                    await db.scalars(select(GraphEntity).where(GraphEntity.id.in_(neighbor_ids)))
                ).all()
            }

        lines: list[str] = []
        seen_edges: set[tuple[uuid.UUID, uuid.UUID, str]] = set()
        for edge in edges:
            key = (edge.source_id, edge.target_id, edge.relation_type)
            if key in seen_edges:
                continue
            seen_edges.add(key)

            source = entities.get(edge.source_id) or neighbor_map.get(edge.source_id)
            target = entities.get(edge.target_id) or neighbor_map.get(edge.target_id)
            if source is None or target is None:
                continue
            lines.append(
                f"- {source.name} --[{edge.relation_type}]--> {target.name}"
            )

        if not lines:
            return None
        return "图谱关联（1-hop）:\n" + "\n".join(lines)

    async def enrich_from_rag(
        self,
        db: AsyncSession,
        rag_results: list[dict],
    ) -> tuple[str | None, list[str]]:
        """Link entities from RAG chunks and return 1-hop context + entity names."""
        entity_ids, entity_names = await self.link_entities(db, rag_results)
        context = await self.build_one_hop_context(db, entity_ids)
        return context, entity_names
