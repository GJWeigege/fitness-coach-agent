import uuid

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import GraphEdge, GraphEntity, GraphEntityLink, KnowledgeChunk, KnowledgeDocument
from app.db.seed_graph import COACH_GRAPH_ENTITIES, COACH_GRAPH_EDGES, seed_demo_graph
from app.services.graph_service import GraphService

EMBEDDING_DIM = 1024


def _vec(*head: float) -> list[float]:
    return list(head) + [0.0] * (EMBEDDING_DIM - len(head))


class MockLLM:
    def __init__(self, vectors: list[list[float]] | None = None) -> None:
        self.vectors = vectors or []
        self._call_index = 0

    async def embedding(self, texts: list[str]) -> list[list[float]]:
        if self.vectors:
            if len(self.vectors) == len(texts):
                return self.vectors
            return [self.vectors[0] for _ in texts]
        return [_vec(0.1) for _ in texts]


@pytest.fixture
def graph_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        graph_rag_enabled=True,
    )
    monkeypatch.setattr("app.services.graph_service.get_settings", lambda: settings)
    monkeypatch.setattr("app.db.seed_graph.get_settings", lambda: settings)
    return settings


async def _seed_squat_graph(db_session):
    squat = GraphEntity(
        name="深蹲",
        entity_type="exercise",
        properties={"pattern": "squat"},
        embedding=_vec(1.0, 0.0),
    )
    knee = GraphEntity(
        name="膝盖损伤",
        entity_type="injury",
        properties={"body_part": "knee"},
        embedding=_vec(0.0, 1.0),
    )
    box_squat = GraphEntity(
        name="箱式深蹲",
        entity_type="exercise",
        properties={"pattern": "box_squat"},
        embedding=_vec(0.8, 0.2),
    )
    db_session.add_all([squat, knee, box_squat])
    await db_session.flush()

    db_session.add_all(
        [
            GraphEdge(
                source_id=squat.id,
                target_id=knee.id,
                relation_type="contraindicated_for",
                weight=0.9,
            ),
            GraphEdge(
                source_id=box_squat.id,
                target_id=squat.id,
                relation_type="alternative_for",
                weight=0.8,
            ),
        ]
    )
    await db_session.flush()
    return squat, knee, box_squat


async def _seed_chunk(db_session, *, content: str, embedding: list[float]):
    doc = KnowledgeDocument(
        title="Graph KB",
        source_path="data/knowledge/squat.md",
        content_hash=f"hash-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(doc)
    await db_session.flush()

    chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=0,
        content=content,
        embedding=embedding,
    )
    db_session.add(chunk)
    await db_session.flush()
    return chunk


@pytest.mark.asyncio
async def test_seed_demo_graph_creates_entities_and_edges(db_session, graph_settings):
    imported = await seed_demo_graph(db_session, llm_client=MockLLM())
    await db_session.commit()

    assert imported == len(COACH_GRAPH_ENTITIES) + len(COACH_GRAPH_EDGES)
    entity_count = len((await db_session.scalars(select(GraphEntity))).all())
    edge_count = len((await db_session.scalars(select(GraphEdge))).all())
    assert entity_count == len(COACH_GRAPH_ENTITIES)
    assert edge_count == len(COACH_GRAPH_EDGES)
    assert len(COACH_GRAPH_ENTITIES) >= 30
    assert len(COACH_GRAPH_EDGES) >= 40


@pytest.mark.asyncio
async def test_seed_demo_graph_is_idempotent(db_session, graph_settings):
    first = await seed_demo_graph(db_session, llm_client=MockLLM())
    await db_session.commit()
    second = await seed_demo_graph(db_session, llm_client=MockLLM())
    await db_session.commit()

    assert first == len(COACH_GRAPH_ENTITIES) + len(COACH_GRAPH_EDGES)
    assert second == 0


@pytest.mark.asyncio
async def test_link_entities_from_rag_chunks(db_session, graph_settings):
    squat, _, _ = await _seed_squat_graph(db_session)
    chunk = await _seed_chunk(
        db_session,
        content="深蹲训练时注意膝盖角度，避免内扣。",
        embedding=_vec(1.0, 0.0),
    )
    service = GraphService()

    entity_ids, entity_names = await service.link_entities(
        db_session,
        [{"chunk_id": str(chunk.id), "content": chunk.content}],
    )

    assert squat.id in entity_ids
    assert "深蹲" in entity_names

    links = (await db_session.scalars(select(GraphEntityLink))).all()
    assert len(links) >= 1
    squat_links = [link for link in links if link.entity_id == squat.id]
    assert len(squat_links) == 1
    assert squat_links[0].chunk_id == chunk.id
    assert squat_links[0].confidence >= 0.45


@pytest.mark.asyncio
async def test_build_one_hop_context_includes_neighbors(db_session, graph_settings):
    squat, knee, box_squat = await _seed_squat_graph(db_session)
    service = GraphService()

    context = await service.build_one_hop_context(db_session, [squat.id])

    assert context is not None
    assert "图谱关联（1-hop）" in context
    assert "深蹲" in context
    assert "膝盖损伤" in context
    assert "contraindicated_for" in context
    assert box_squat.name in context or "alternative_for" in context


@pytest.mark.asyncio
async def test_enrich_from_rag_links_and_builds_context(db_session, graph_settings):
    squat, knee, _ = await _seed_squat_graph(db_session)
    chunk = await _seed_chunk(
        db_session,
        content="膝盖不适时如何调整深蹲？",
        embedding=_vec(1.0, 0.0),
    )
    service = GraphService()

    context, names = await service.enrich_from_rag(
        db_session,
        [{"chunk_id": str(chunk.id), "content": chunk.content}],
    )

    assert "深蹲" in names
    assert context is not None
    assert squat.name in context
    assert knee.name in context
