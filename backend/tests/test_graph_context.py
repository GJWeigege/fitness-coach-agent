import uuid

import pytest

from app.agent.coach.graph_context import (
    append_graph_to_system,
    build_system_with_graph_context,
    format_graph_context_block,
    resolve_graph_context_for_rag,
)
from app.core.config import Settings
from app.db.models import GraphEdge, GraphEntity, KnowledgeChunk, KnowledgeDocument
from app.prompts.coach_system_prompt import COACH_SYSTEM_PROMPT
from app.services.graph_service import GraphService

EMBEDDING_DIM = 1024


def _vec(*head: float) -> list[float]:
    return list(head) + [0.0] * (EMBEDDING_DIM - len(head))


class MockLLM:
    async def embedding(self, texts: list[str]) -> list[list[float]]:
        return [_vec(0.1) for _ in texts]


async def _seed_graph_and_chunk(db_session):
    squat = GraphEntity(
        name="深蹲",
        entity_type="exercise",
        embedding=_vec(1.0, 0.0),
    )
    knee = GraphEntity(
        name="膝盖损伤",
        entity_type="injury",
        embedding=_vec(0.0, 1.0),
    )
    db_session.add_all([squat, knee])
    await db_session.flush()
    db_session.add(
        GraphEdge(
            source_id=squat.id,
            target_id=knee.id,
            relation_type="contraindicated_for",
            weight=0.9,
        )
    )
    await db_session.flush()

    doc = KnowledgeDocument(
        title="ctx-doc",
        source_path="data/knowledge/squat.md",
        content_hash=f"hash-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(doc)
    await db_session.flush()
    chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=0,
        content="深蹲与膝盖损伤注意事项。",
        embedding=_vec(1.0, 0.0),
    )
    db_session.add(chunk)
    await db_session.flush()
    return chunk


@pytest.fixture
def graph_context_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        graph_rag_enabled=True,
    )
    monkeypatch.setattr("app.agent.coach.graph_context.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.graph_service.get_settings", lambda: settings)
    return settings


def test_format_graph_context_block():
    assert format_graph_context_block(None) == ""
    assert "【图谱补充】" in format_graph_context_block("深蹲 --[禁忌]--> 膝盖损伤")


@pytest.mark.asyncio
async def test_append_graph_to_system_when_enabled(db_session, graph_context_settings):
    chunk = await _seed_graph_and_chunk(db_session)
    rag_results = [{"chunk_id": str(chunk.id), "content": chunk.content}]
    service = GraphService()

    graph_context, names = await resolve_graph_context_for_rag(
        db_session,
        rag_results,
        graph_service=service,
    )
    system = append_graph_to_system(COACH_SYSTEM_PROMPT, graph_context)

    assert graph_context is not None
    assert "深蹲" in names
    assert "【图谱补充】" in system
    assert "图谱关联（1-hop）" in system
    assert COACH_SYSTEM_PROMPT in system


@pytest.mark.asyncio
async def test_graph_context_skipped_when_disabled(db_session, monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        graph_rag_enabled=False,
    )
    monkeypatch.setattr("app.agent.coach.graph_context.get_settings", lambda: settings)

    chunk = await _seed_graph_and_chunk(db_session)
    graph_context, names = await resolve_graph_context_for_rag(
        db_session,
        [{"chunk_id": str(chunk.id), "content": chunk.content}],
    )
    system = append_graph_to_system(COACH_SYSTEM_PROMPT, graph_context)

    assert graph_context is None
    assert names == []
    assert "【图谱补充】" not in system
    assert system == COACH_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_build_system_with_graph_context(db_session, graph_context_settings):
    chunk = await _seed_graph_and_chunk(db_session)
    rag_results = [{"chunk_id": str(chunk.id), "content": chunk.content}]

    system, names = await build_system_with_graph_context(
        db_session,
        COACH_SYSTEM_PROMPT,
        rag_results,
        graph_service=GraphService(),
    )

    assert "深蹲" in names
    assert "【图谱补充】" in system
    assert "contraindicated_for" in system
