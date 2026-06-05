import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.db.seed_knowledge import (
    COACH_KNOWLEDGE_FILES,
    KNOWLEDGE_DIR,
    _resolve_knowledge_files,
    seed_demo_knowledge,
)

settings = get_settings()
EMBED_DIM = settings.embedding_dim


class MockLLM:
    async def embedding(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * EMBED_DIM for _ in texts]


def test_knowledge_dir_has_five_coach_markdown_files():
    files = _resolve_knowledge_files()
    assert len(files) == len(COACH_KNOWLEDGE_FILES)
    assert [path.name for path in files] == list(COACH_KNOWLEDGE_FILES)
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert 500 <= len(text) <= 1500, f"{path.name} length={len(text)}"
        assert KNOWLEDGE_DIR in path.parents


@pytest.mark.asyncio
async def test_seed_demo_knowledge_imports_all_files(db_session):
    imported = await seed_demo_knowledge(db_session, llm_client=MockLLM())
    await db_session.commit()

    assert imported == len(COACH_KNOWLEDGE_FILES)
    doc_count = await db_session.scalar(select(func.count()).select_from(KnowledgeDocument))
    chunk_count = await db_session.scalar(select(func.count()).select_from(KnowledgeChunk))
    assert doc_count == len(COACH_KNOWLEDGE_FILES)
    assert chunk_count >= len(COACH_KNOWLEDGE_FILES)


@pytest.mark.asyncio
async def test_seed_demo_knowledge_is_idempotent(db_session):
    first = await seed_demo_knowledge(db_session, llm_client=MockLLM())
    await db_session.commit()
    second = await seed_demo_knowledge(db_session, llm_client=MockLLM())
    await db_session.commit()

    assert first == len(COACH_KNOWLEDGE_FILES)
    assert second == 0
    doc_count = await db_session.scalar(select(func.count()).select_from(KnowledgeDocument))
    assert doc_count == len(COACH_KNOWLEDGE_FILES)
