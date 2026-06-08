from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.services.ingest_service import IngestService

settings = get_settings()
EMBED_DIM = settings.embedding_dim


class MockLLM:
    async def embedding(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * EMBED_DIM for _ in texts]


def test_split_text_produces_chunks():
    service = IngestService(llm_client=MockLLM())  # type: ignore[arg-type]
    text = "\n".join([f"段落{i} " + ("x" * 120) for i in range(1, 8)])
    chunks = service._split_text(text, max_chars=200, overlap=40)
    assert len(chunks) >= 3
    assert all(len(chunk) <= 200 for chunk in chunks)


def test_split_text_uses_settings_defaults():
    service = IngestService(llm_client=MockLLM())  # type: ignore[arg-type]
    assert service.chunk_size == settings.ingest_chunk_size
    assert service.chunk_overlap == settings.ingest_chunk_overlap
    long_para = "y" * (settings.ingest_chunk_size + 50)
    chunks = service._split_text(long_para)
    assert len(chunks) >= 2
    assert all(len(chunk) <= settings.ingest_chunk_size for chunk in chunks)


def test_split_markdown_by_sections_includes_title_prefix():
    service = IngestService(llm_client=MockLLM())  # type: ignore[arg-type]
    text = """# 上下肢分化训练

## 四日上下肢分化
- 周一训练

## 两日上下肢
- 周一上肢
"""
    chunks = service._split_text(text)
    assert len(chunks) == 2
    assert all("# 上下肢分化训练" in chunk for chunk in chunks)
    assert any("## 四日上下肢分化" in chunk for chunk in chunks)
    assert any("## 两日上下肢" in chunk for chunk in chunks)


def test_split_markdown_merges_short_preamble_into_first_section():
    service = IngestService(llm_client=MockLLM())  # type: ignore[arg-type]
    text = """# 标题

简短导语。

## 第一节
内容一
"""
    chunks = service._split_text(text)
    assert len(chunks) == 1
    assert "简短导语" in chunks[0]
    assert "## 第一节" in chunks[0]
    assert "# 标题" in chunks[0]


def test_split_markdown_keeps_long_preamble_as_first_chunk():
    service = IngestService(llm_client=MockLLM())  # type: ignore[arg-type]
    preamble = "导语" * 30
    text = f"""# 标题

{preamble}

## 第一节
内容一
"""
    chunks = service._split_text(text)
    assert len(chunks) == 2
    assert preamble in chunks[0]
    assert "## 第一节" not in chunks[0]
    assert "## 第一节" in chunks[1]


@pytest.mark.asyncio
async def test_ingest_file_creates_document_and_chunks(db_session, tmp_path: Path):
    content = "\n".join([f"训练建议段落{i} " + ("z" * 100) for i in range(1, 6)])
    file_path = tmp_path / "coach-tips.md"
    file_path.write_text(content, encoding="utf-8")

    service = IngestService(llm_client=MockLLM())  # type: ignore[arg-type]
    doc, chunk_count = await service.ingest_file(db_session, file_path, title="Coach Tips")

    assert chunk_count == len(service._split_text(content))
    assert doc.title == "Coach Tips"
    assert doc.status == "indexed"

    doc_count = await db_session.scalar(select(func.count()).select_from(KnowledgeDocument))
    chunk_rows = await db_session.scalar(select(func.count()).select_from(KnowledgeChunk))
    assert doc_count == 1
    assert chunk_rows == chunk_count

    stored_chunks = (
        await db_session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.chunk_index)
        )
    ).all()
    assert len(stored_chunks) == chunk_count
    assert [c.chunk_index for c in stored_chunks] == list(range(chunk_count))
