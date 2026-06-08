import hashlib
import re
from pathlib import Path
from uuid import UUID

from pypdf import PdfReader
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.llm.dashscope_client import DashScopeClient

_PREAMBLE_STANDALONE_MIN_CHARS = 50


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
        if re.search(r"^##\s", text, re.MULTILINE):
            return self._split_markdown_by_sections(text, max_chars, overlap)
        return self._split_by_paragraphs(text, max_chars, overlap)

    def _split_markdown_by_sections(
        self,
        text: str,
        max_chars: int,
        overlap: int,
    ) -> list[str]:
        lines = text.splitlines()
        doc_title: str | None = None
        preamble_lines: list[str] = []
        sections: list[tuple[str, list[str]]] = []
        current_heading: str | None = None
        current_body: list[str] = []

        index = 0
        while index < len(lines):
            line = lines[index]
            if line.startswith("# ") and not line.startswith("## "):
                doc_title = line.strip()
                index += 1
                break
            index += 1

        while index < len(lines):
            line = lines[index]
            if line.startswith("## "):
                break
            if line.strip():
                preamble_lines.append(line.rstrip())
            index += 1

        while index < len(lines):
            line = lines[index]
            if line.startswith("## "):
                if current_heading is not None:
                    sections.append((current_heading, current_body))
                current_heading = line.rstrip()
                current_body = []
            elif current_heading is not None:
                current_body.append(line.rstrip())
            index += 1
        if current_heading is not None:
            sections.append((current_heading, current_body))

        if not sections:
            return self._split_by_paragraphs(text, max_chars, overlap)

        chunks: list[str] = []
        preamble_text = "\n".join(preamble_lines).strip()
        merge_preamble_into_first = (
            bool(preamble_text)
            and len(preamble_text) < _PREAMBLE_STANDALONE_MIN_CHARS
        )

        if preamble_text and not merge_preamble_into_first:
            chunks.extend(self._pack_text(doc_title, preamble_text, max_chars, overlap))

        for section_index, (heading, body_lines) in enumerate(sections):
            body = "\n".join(body_lines).strip()
            section_body = f"{heading}\n{body}" if body else heading
            if merge_preamble_into_first and section_index == 0:
                section_body = f"{preamble_text}\n\n{section_body}"
            chunks.extend(
                self._pack_text(doc_title, section_body, max_chars, overlap)
            )

        return chunks

    def _pack_text(
        self,
        doc_title: str | None,
        body: str,
        max_chars: int,
        overlap: int,
    ) -> list[str]:
        block = self._compose_block(doc_title, body)
        if len(block) <= max_chars:
            return [block]
        return self._split_long_block(doc_title, body, max_chars, overlap)

    def _compose_block(self, doc_title: str | None, body: str) -> str:
        parts = [part.strip() for part in (doc_title, body) if part and part.strip()]
        return "\n\n".join(parts)

    def _split_long_block(
        self,
        doc_title: str | None,
        body: str,
        max_chars: int,
        overlap: int,
    ) -> list[str]:
        header = self._compose_block(doc_title, "")
        header_budget = len(header) + (2 if header else 0)
        body_budget = max_chars - header_budget
        if body_budget < 80:
            return self._split_by_char_window(self._compose_block(doc_title, body), max_chars, overlap)

        chunks: list[str] = []
        paragraphs = [paragraph.strip() for paragraph in body.split("\n") if paragraph.strip()]
        current = ""
        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 1 <= body_budget:
                current = f"{current}\n{paragraph}".strip()
                continue
            if current:
                chunks.append(self._compose_block(doc_title, current))
            if len(paragraph) <= body_budget:
                current = paragraph
            else:
                for piece in self._split_by_char_window(paragraph, body_budget, overlap):
                    chunks.append(self._compose_block(doc_title, piece))
                current = ""
        if current:
            chunks.append(self._compose_block(doc_title, current))
        return chunks

    def _split_by_paragraphs(
        self,
        text: str,
        max_chars: int,
        overlap: int,
    ) -> list[str]:
        paragraphs = [paragraph.strip() for paragraph in text.split("\n") if paragraph.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            if len(current) + len(paragraph) + 1 <= max_chars:
                current = f"{current}\n{paragraph}".strip()
                continue
            if current:
                chunks.append(current)
            if len(paragraph) <= max_chars:
                current = paragraph
            else:
                chunks.extend(self._split_by_char_window(paragraph, max_chars, overlap))
                current = ""
        if current:
            chunks.append(current)
        return chunks

    def _split_by_char_window(self, text: str, max_chars: int, overlap: int) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            chunks.append(text[start : start + max_chars])
            start += max(max_chars - overlap, 1)
        return chunks
