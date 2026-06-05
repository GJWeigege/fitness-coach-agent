import hashlib
from pathlib import Path
from uuid import UUID

from pypdf import PdfReader
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.llm.dashscope_client import DashScopeClient


class IngestService:
    def __init__(self, llm_client: DashScopeClient) -> None:
        self.llm_client = llm_client
        settings = get_settings()
        self.chunk_size = settings.ingest_chunk_size
        self.chunk_overlap = settings.ingest_chunk_overlap

    async def ingest_pending_document(
        self, db: AsyncSession, document_id: UUID, file_path: Path
    ) -> tuple[KnowledgeDocument, int]:
        doc = await db.get(KnowledgeDocument, document_id)
        if doc is None:
            raise ValueError("文档不存在。")

        text = self._extract_text(file_path)
        chunks = self._split_text(text)
        if not chunks:
            raise ValueError("文档内容为空，无法建立索引。")

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc.content_hash = content_hash
        doc.status = "indexed"

        embeddings = await self.llm_client.embedding(chunks)
        for idx, chunk_text in enumerate(chunks):
            db.add(
                KnowledgeChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    content=chunk_text,
                    embedding=embeddings[idx],
                )
            )
        await db.flush()
        return doc, len(chunks)

    async def ingest_file(
        self, db: AsyncSession, file_path: Path, title: str | None = None
    ) -> tuple[KnowledgeDocument, int]:
        text = self._extract_text(file_path)
        chunks = self._split_text(text)
        if not chunks:
            raise ValueError("文档内容为空，无法建立索引。")

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        doc = KnowledgeDocument(
            title=title or file_path.name,
            source_path=str(file_path),
            content_hash=content_hash,
            status="indexed",
        )
        db.add(doc)
        await db.flush()

        embeddings = await self.llm_client.embedding(chunks)
        for idx, chunk_text in enumerate(chunks):
            db.add(
                KnowledgeChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    content=chunk_text,
                    embedding=embeddings[idx],
                )
            )
        await db.flush()
        return doc, len(chunks)

    async def reindex_document(self, db: AsyncSession, document_id: UUID) -> tuple[KnowledgeDocument, int]:
        doc = await db.get(KnowledgeDocument, document_id)
        if doc is None:
            raise ValueError("文档不存在。")
        source_path = Path(doc.source_path)
        if not source_path.exists():
            raise ValueError("源文件不存在，无法重建索引。")

        text = self._extract_text(source_path)
        chunks = self._split_text(text)
        if not chunks:
            raise ValueError("文档内容为空，无法建立索引。")
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
        embeddings = await self.llm_client.embedding(chunks)
        for idx, chunk_text in enumerate(chunks):
            db.add(
                KnowledgeChunk(
                    document_id=doc.id,
                    chunk_index=idx,
                    content=chunk_text,
                    embedding=embeddings[idx],
                )
            )
        doc.content_hash = content_hash
        doc.status = "indexed"
        await db.flush()
        return doc, len(chunks)

    def _extract_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix in {".txt", ".md"}:
            return file_path.read_text(encoding="utf-8")
        if suffix == ".pdf":
            reader = PdfReader(str(file_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        raise ValueError(f"暂不支持的文件类型: {suffix}")

    def _split_text(
        self,
        text: str,
        max_chars: int | None = None,
        overlap: int | None = None,
    ) -> list[str]:
        max_chars = max_chars if max_chars is not None else self.chunk_size
        overlap = overlap if overlap is not None else self.chunk_overlap
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks: list[str] = []
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 1 <= max_chars:
                current = f"{current}\n{para}".strip()
                continue
            if current:
                chunks.append(current)
            if len(para) <= max_chars:
                current = para
            else:
                start = 0
                while start < len(para):
                    chunks.append(para[start : start + max_chars])
                    start += max(max_chars - overlap, 1)
                current = ""
        if current:
            chunks.append(current)
        return chunks
