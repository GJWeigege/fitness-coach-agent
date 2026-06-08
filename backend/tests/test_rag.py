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

    async def embedding(self, texts: list[str]) -> list[list[float]]:
        return [self.query_vector for _ in texts]


@pytest.fixture
def rag_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        rag_top_k=3,
        rag_hybrid_enabled=True,
        rag_keyword_top_k=12,
        rag_vector_candidate_k=20,
        rag_vector_score_min=0.55,
        rag_vector_score_min_with_keyword=0.45,
        rag_keyword_top_for_filter=3,
        rag_vector_top_for_filter=10,
        rag_max_chunks_per_document=2,
        rag_rerank_enabled=False,
        rag_mmr_enabled=False,
        rag_score_threshold=0.35,
    )
    monkeypatch.setattr("app.services.rag_service.get_settings", lambda: settings)
    monkeypatch.setattr("app.agent.guardrails.get_settings", lambda: settings)
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
        chunk_index=5,
        content="硬拉动作要点：髋铰链主导，背部保持中立。",
        embedding=_vec(1.0, 0.0),
    )
    noise_chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=10,
        content="有氧恢复日建议低强度骑行或散步。",
        embedding=_vec(0.0, 0.0, 1.0),
    )
    db_session.add_all([keyword_chunk, vector_chunk, noise_chunk])
    await db_session.flush()
    return keyword_chunk, vector_chunk, noise_chunk


def test_query_terms_splits_long_chinese_phrases(rag_settings):
    rag = RagService(llm_client=MockLLM(_vec(1.0)))
    terms = rag._query_terms("深蹲硬拉")
    assert "深蹲" in terms
    assert "硬拉" in terms


def test_escape_ilike_term_escapes_wildcards(rag_settings):
    rag = RagService(llm_client=MockLLM(_vec(1.0)))
    assert rag._escape_ilike_term("100%") == "100\\%"
    assert rag._escape_ilike_term("a_b") == "a\\_b"
    assert rag._escape_ilike_term("a\\b") == "a\\\\b"


def test_rrf_merge_boosts_overlap(rag_settings):
    rag = RagService(llm_client=MockLLM(_vec(1.0)))
    keyword = [
        {
            "chunk_id": "a",
            "document_id": "d1",
            "chunk_index": 0,
            "content": "A",
            "score": 0.01,
            "keyword_hit": True,
            "source": "keyword",
        },
        {
            "chunk_id": "b",
            "document_id": "d1",
            "chunk_index": 1,
            "content": "B",
            "score": 0.01,
            "keyword_hit": True,
            "source": "keyword",
        },
    ]
    vector = [
        {
            "chunk_id": "b",
            "document_id": "d1",
            "chunk_index": 1,
            "content": "B",
            "score": 0.9,
            "vector_score": 0.9,
            "source": "vector",
        },
        {
            "chunk_id": "c",
            "document_id": "d1",
            "chunk_index": 2,
            "content": "C",
            "score": 0.8,
            "vector_score": 0.8,
            "source": "vector",
        },
    ]

    merged = rag._rrf_merge(keyword, vector)

    assert [item["chunk_id"] for item in merged[:3]] == ["b", "a", "c"]
    assert merged[0]["vector_score"] == 0.9
    assert merged[0]["keyword_hit"] is True
    assert all(item["source"] == "hybrid" for item in merged[:3])


def test_filter_results_requires_vector_or_keyword_signal(rag_settings):
    rag = RagService(llm_client=MockLLM(_vec(1.0)))
    candidates = [
        {
            "chunk_id": "strong",
            "document_id": "d1",
            "chunk_index": 0,
            "content": "高相关",
            "score": 0.16,
            "vector_score": 0.72,
            "keyword_hit": True,
            "source": "hybrid",
        },
        {
            "chunk_id": "weak",
            "document_id": "d1",
            "chunk_index": 5,
            "content": "弱相关",
            "score": 0.15,
            "vector_score": 0.2,
            "keyword_hit": False,
            "source": "hybrid",
        },
        {
            "chunk_id": "keyword-only",
            "document_id": "d1",
            "chunk_index": 6,
            "content": "关键词命中",
            "score": 0.14,
            "vector_score": 0.0,
            "keyword_hit": True,
            "source": "hybrid",
        },
    ]

    filtered = rag._filter_results(
        candidates,
        keyword_top_ids={"keyword-only"},
        vector_top_ids=set(),
    )

    assert [item["chunk_id"] for item in filtered] == ["strong", "keyword-only"]


def test_apply_per_document_limit_skips_adjacent_chunks(rag_settings):
    rag = RagService(llm_client=MockLLM(_vec(1.0)))
    results = [
        {
            "chunk_id": "a",
            "document_id": "d1",
            "chunk_index": 0,
            "content": "A",
            "vector_score": 0.9,
        },
        {
            "chunk_id": "b",
            "document_id": "d1",
            "chunk_index": 1,
            "content": "B",
            "vector_score": 0.85,
        },
        {
            "chunk_id": "c",
            "document_id": "d1",
            "chunk_index": 3,
            "content": "C",
            "vector_score": 0.8,
        },
    ]

    limited = rag._apply_per_document_limit(results)

    assert [item["chunk_id"] for item in limited] == ["a", "c"]


@pytest.mark.asyncio
async def test_hybrid_retrieve_combines_keyword_and_vector(db_session, rag_settings):
    keyword_chunk, vector_chunk, _ = await _seed_chunks(db_session)
    rag = RagService(llm_client=MockLLM(_vec(1.0, 0.0)))

    results = await rag.retrieve(db_session, "深蹲硬拉")

    chunk_ids = {item["chunk_id"] for item in results}
    assert str(keyword_chunk.id) in chunk_ids
    assert str(vector_chunk.id) in chunk_ids
    assert results[0]["source"] == "hybrid"
    assert "vector_score" in results[0]

    log_rows = (await db_session.execute(select(RetrievalLog))).scalars().all()
    assert len(log_rows) == 1
    assert log_rows[0].results["hybrid"] is True
    assert len(log_rows[0].results["items"]) == len(results)


@pytest.mark.asyncio
async def test_vector_only_when_hybrid_disabled(db_session, monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        rag_top_k=3,
        rag_hybrid_enabled=False,
        rag_keyword_top_k=12,
        rag_vector_candidate_k=20,
        rag_vector_score_min=0.55,
        rag_rerank_enabled=False,
        rag_mmr_enabled=False,
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
async def test_vector_only_excludes_sub_threshold_chunks(db_session, monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        rag_top_k=3,
        rag_hybrid_enabled=False,
        rag_vector_candidate_k=20,
        rag_vector_score_min=0.55,
        rag_rerank_enabled=False,
        rag_mmr_enabled=False,
    )
    monkeypatch.setattr("app.services.rag_service.get_settings", lambda: settings)

    doc = KnowledgeDocument(
        title="Threshold KB",
        source_path="data/knowledge/threshold.md",
        content_hash="hash-threshold",
    )
    db_session.add(doc)
    await db_session.flush()

    strong_chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=0,
        content="高相关硬拉要点",
        embedding=_vec(1.0, 0.0),
    )
    weak_chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=1,
        content="低相关恢复建议",
        embedding=_vec(0.0, 1.0),
    )
    db_session.add_all([strong_chunk, weak_chunk])
    await db_session.flush()

    rag = RagService(llm_client=MockLLM(_vec(1.0, 0.0)))
    results = await rag.retrieve(db_session, "硬拉", top_k=3)

    chunk_ids = {item["chunk_id"] for item in results}
    assert str(strong_chunk.id) in chunk_ids
    assert str(weak_chunk.id) not in chunk_ids


@pytest.mark.asyncio
async def test_vector_search_uses_mocked_embeddings(db_session, rag_settings):
    keyword_chunk, vector_chunk, noise_chunk = await _seed_chunks(db_session)
    llm = MockLLM(_vec(1.0, 0.0))
    rag = RagService(llm_client=llm)

    hits = await rag._vector_search(db_session, "deadlift form", top_k=3)

    assert hits[0]["chunk_id"] == str(vector_chunk.id)
    assert hits[0]["source"] == "vector"
    assert hits[0]["vector_score"] == hits[0]["score"]
    assert hits[0]["vector_score"] > hits[1]["vector_score"]
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
    assert hits[0]["keyword_hit"] is True


@pytest.mark.asyncio
async def test_keyword_search_does_not_expand_underscore_wildcards(db_session, monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        rag_top_k=3,
        rag_hybrid_enabled=True,
        rag_rerank_enabled=False,
        rag_mmr_enabled=False,
    )
    monkeypatch.setattr("app.services.rag_service.get_settings", lambda: settings)

    doc = KnowledgeDocument(
        title="Wildcard KB",
        source_path="data/knowledge/wildcard.md",
        content_hash="hash-wildcard",
    )
    db_session.add(doc)
    await db_session.flush()

    literal_chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=0,
        content="动作 a_b 训练",
        embedding=_vec(0.0, 1.0),
    )
    expanded_chunk = KnowledgeChunk(
        document_id=doc.id,
        chunk_index=1,
        content="动作 axb 训练",
        embedding=_vec(0.0, 1.0),
    )
    db_session.add_all([literal_chunk, expanded_chunk])
    await db_session.flush()

    rag = RagService(llm_client=MockLLM(_vec(1.0, 0.0)))
    hits = await rag._keyword_search(db_session, "a_b", top_k=4)

    chunk_ids = {hit["chunk_id"] for hit in hits}
    assert str(literal_chunk.id) in chunk_ids
    assert str(expanded_chunk.id) not in chunk_ids


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


def test_mmr_select_prefers_diverse_chunks(rag_settings):
    rag = RagService(llm_client=MockLLM(_vec(1.0)))
    candidates = [
        {
            "chunk_id": "a",
            "document_id": "d1",
            "chunk_index": 0,
            "content": "A",
            "vector_score": 0.9,
        },
        {
            "chunk_id": "b",
            "document_id": "d1",
            "chunk_index": 1,
            "content": "B",
            "vector_score": 0.88,
        },
        {
            "chunk_id": "c",
            "document_id": "d2",
            "chunk_index": 0,
            "content": "C",
            "vector_score": 0.7,
        },
    ]
    embeddings = {
        "a": _vec(1.0, 0.0),
        "b": _vec(0.99, 0.01),
        "c": _vec(0.0, 1.0),
    }

    selected = rag._mmr_select(candidates, embeddings, top_k=2)

    assert [item["chunk_id"] for item in selected] == ["a", "c"]


@pytest.mark.asyncio
async def test_apply_rerank_reorders_candidates(rag_settings):
    class MockLLMWithRerank(MockLLM):
        async def rerank(self, query: str, documents: list[str], *, top_n: int | None = None):
            return [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.6},
            ]

    rag = RagService(llm_client=MockLLMWithRerank(_vec(1.0)))
    candidates = [
        {"chunk_id": "a", "content": "first", "vector_score": 0.5},
        {"chunk_id": "b", "content": "second", "vector_score": 0.9},
    ]

    reranked = await rag._apply_rerank("query", candidates)

    assert [item["chunk_id"] for item in reranked] == ["b", "a"]
    assert reranked[0]["rerank_score"] == 0.95


@pytest.mark.asyncio
async def test_apply_rerank_empty_response_falls_back(rag_settings):
    class MockLLMEmptyRerank(MockLLM):
        async def rerank(self, query: str, documents: list[str], *, top_n: int | None = None):
            return []

    rag = RagService(llm_client=MockLLMEmptyRerank(_vec(1.0)))
    candidates = [
        {"chunk_id": "a", "content": "first", "vector_score": 0.5},
        {"chunk_id": "b", "content": "second", "vector_score": 0.9},
    ]

    reranked = await rag._apply_rerank("query", candidates)

    assert [item["chunk_id"] for item in reranked] == ["a", "b"]


@pytest.mark.asyncio
async def test_apply_rerank_partial_response_appends_unranked(rag_settings):
    class MockLLMPartialRerank(MockLLM):
        async def rerank(self, query: str, documents: list[str], *, top_n: int | None = None):
            return [{"index": 1, "relevance_score": 0.95}]

    rag = RagService(llm_client=MockLLMPartialRerank(_vec(1.0)))
    candidates = [
        {"chunk_id": "a", "content": "first", "vector_score": 0.5},
        {"chunk_id": "b", "content": "second", "vector_score": 0.9},
    ]

    reranked = await rag._apply_rerank("query", candidates)

    assert [item["chunk_id"] for item in reranked] == ["b", "a"]
    assert reranked[0]["rerank_score"] == 0.95
    assert "rerank_score" not in reranked[1]


def test_mmr_select_handles_missing_embeddings(rag_settings):
    rag = RagService(llm_client=MockLLM(_vec(1.0)))
    candidates = [
        {"chunk_id": "a", "document_id": "d1", "chunk_index": 0, "content": "A", "vector_score": 0.9},
        {"chunk_id": "b", "document_id": "d1", "chunk_index": 2, "content": "B", "vector_score": 0.8},
    ]
    embeddings = {"a": _vec(1.0, 0.0)}

    selected = rag._mmr_select(candidates, embeddings, top_k=2)

    assert len(selected) == 2
    assert selected[0]["chunk_id"] == "a"


def test_finalize_results_applies_per_document_limit_after_mmr(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        embedding_dim=EMBEDDING_DIM,
        rag_top_k=3,
        rag_hybrid_enabled=True,
        rag_rerank_enabled=False,
        rag_mmr_enabled=True,
        rag_mmr_lambda=0.7,
        rag_max_chunks_per_document=1,
        rag_rerank_candidate_k=15,
    )
    monkeypatch.setattr("app.services.rag_service.get_settings", lambda: settings)

    rag = RagService(llm_client=MockLLM(_vec(1.0)))
    candidates = [
        {"chunk_id": "a", "document_id": "d1", "chunk_index": 0, "content": "A", "vector_score": 0.9},
        {"chunk_id": "b", "document_id": "d1", "chunk_index": 5, "content": "B", "vector_score": 0.85},
        {"chunk_id": "c", "document_id": "d2", "chunk_index": 0, "content": "C", "vector_score": 0.7},
    ]
    embeddings = {
        "a": _vec(1.0, 0.0),
        "b": _vec(0.0, 1.0),
        "c": _vec(0.0, 0.0, 1.0),
    }

    async def fake_load(_db, chunk_ids):
        return {cid: embeddings[cid] for cid in chunk_ids if cid in embeddings}

    rag._load_chunk_embeddings = fake_load  # type: ignore[method-assign]

    import asyncio

    finalized = asyncio.run(rag._finalize_results(None, "query", candidates, top_k=3))  # type: ignore[arg-type]

    doc_ids = [item["document_id"] for item in finalized]
    assert doc_ids.count("d1") <= 1

