import uuid
import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db.models import KnowledgeChunk, KnowledgeDocument, RetrievalLog
from app.services.rag_service import RagService

EMBEDDING_DIM = 1024


def _vec(*head: float) -> list[float]:
    return list(head) + [0.0] * (EMBEDDING_DIM - len(head))


class MockLLM:
    def __init__(self, query_vector: list[float]) -> None:
        self.query_vector = query_vector

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self.query_vector for _ in texts]


@pytest.fixture
def rag_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        rag_top_k=4,
        rag_hybrid_enabled=True,
        rag_keyword_top_k=8,
        rag_score_threshold=0.35,
    )
    monkeypatch.setattr("app.services.rag_service.get_settings", lambda: settings)
    return settings


async def _seed_chunks(db_session):
    doc = KnowledgeDocument(
        title="Coach KB",
        source_path="data/knowledge/squat.md",
        content_hash="hash-squat",
    )
    db_session.add(doc)
    await db_session.flush()

    keyword_chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=0,
        content="深蹲训练时注意膝盖与脚尖方向一致，避免内扣。",
        embedding=_vec(0.0, 1.0),
    )
    vector_chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=1,
        content="硬拉动作要点：髋铰链主导，背部保持中立。",
        embedding=_vec(1.0, 0.0),
    )
    noise_chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=2,
        content="有氧恢复日建议低强度骑行或散步。",
        embedding=_vec(0.0, 0.0, 1.0),
    )
    db_session.add_all([keyword_chunk, vector_chunk, noise_chunk])
    await db_session.flush()
    return keyword_chunk, vector_chunk, noise_chunk


def test_rrf_merge_boosts_overlap(rag_settings):
    rag = RagService(llm_client=MockLLM(_vec(1.0)))
    keyword = [
        {"chunk_id": "a", "document_id": "d1", "chunk_index": 0, "content": "A", "score": 0.01, "source": "keyword"},
        {"chunk_id": "b", "document_id": "d1", "chunk_index": 1, "content": "B", "score": 0.01, "source": "keyword"},
    ]
    vector = [
        {"chunk_id": "b", "document_id": "d1", "chunk_index": 1, "content": "B", "score": 0.9, "source": "vector"},
        {"chunk_id": "c", "document_id": "d1", "chunk_index": 2, "content": "C", "score": 0.8, "source": "vector"},
    ]

    merged = rag._rrf_merge(keyword, vector, top_k=3)

    assert [item["chunk_id"] for item in merged] == ["b", "a", "c"]
    assert all(item["source"] == "hybrid" for item in merged)


@pytest.mark.asyncio
async def test_hybrid_retrieve_combines_keyword_and_vector(db_session, rag_settings):
    keyword_chunk, vector_chunk, _ = await _seed_chunks(db_session)
    rag = RagService(llm_client=MockLLM(_vec(1.0, 0.0)))

    results = await rag.retrieve(db_session, "深蹲硬拉")

    chunk_ids = {item["chunk_id"] for item in results}
    assert str(keyword_chunk.id) in chunk_ids
    assert str(vector_chunk.id) in chunk_ids
    assert results[0]["source"] == "hybrid"

    log_rows = (await db_session.execute(select(RetrievalLog))).scalars().all()
    assert len(log_rows) == 1
    assert log_rows[0].results["hybrid"] is True
    assert len(log_rows[0].results["items"]) == len(results)


@pytest.mark.asyncio
async def test_vector_only_when_hybrid_disabled(db_session, monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        rag_top_k=4,
        rag_hybrid_enabled=False,
        rag_keyword_top_k=8,
        rag_score_threshold=0.35,
    )
    monkeypatch.setattr("app.services.rag_service.get_settings", lambda: settings)

    keyword_chunk, vector_chunk, _ = await _seed_chunks(db_session)
    rag = RagService(llm_client=MockLLM(_vec(1.0, 0.0)))

    results = await rag.retrieve(db_session, "深蹲硬拉", top_k=1)

    assert len(results) == 1
    assert results[0]["chunk_id"] == str(vector_chunk.id)
    assert results[0]["source"] == "vector"
    assert results[0]["chunk_id"] != str(keyword_chunk.id)


@pytest.mark.asyncio
async def test_vector_search_uses_mocked_embeddings(db_session, rag_settings):
    keyword_chunk, vector_chunk, noise_chunk = await _seed_chunks(db_session)
    llm = MockLLM(_vec(1.0, 0.0))
    rag = RagService(llm_client=llm)

    hits = await rag._vector_search(db_session, "deadlift form", top_k=3)

    assert hits[0]["chunk_id"] == str(vector_chunk.id)
    assert hits[0]["source"] == "vector"
    assert hits[0]["score"] > hits[1]["score"]
    trailing_ids = {item["chunk_id"] for item in hits[1:]}
    assert trailing_ids == {str(keyword_chunk.id), str(noise_chunk.id)}


@pytest.mark.asyncio
async def test_keyword_search_matches_terms(db_session, rag_settings):
    keyword_chunk, _, _ = await _seed_chunks(db_session)
    rag = RagService(llm_client=MockLLM(_vec(1.0)))

    hits = await rag._keyword_search(db_session, "深蹲训练", top_k=4)

    assert len(hits) == 1
    assert hits[0]["chunk_id"] == str(keyword_chunk.id)
    assert hits[0]["source"] == "keyword"


@pytest.mark.asyncio
async def test_retrieve_passes_session_metadata(db_session, rag_settings):
    await _seed_chunks(db_session)
    rag = RagService(llm_client=MockLLM(_vec(1.0, 0.0)))
    session_id = uuid.uuid4()
    message_id = uuid.uuid4()

    await rag.retrieve(db_session, "深蹲", session_id=session_id, message_id=message_id)

    log_row = (await db_session.execute(select(RetrievalLog))).scalar_one()
    assert log_row.session_id == session_id
    assert log_row.message_id == message_id
    assert log_row.query == "深蹲"
