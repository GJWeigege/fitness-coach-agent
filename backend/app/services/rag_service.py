import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import KnowledgeChunk, RetrievalLog
from app.llm.dashscope_client import DashScopeClient


class RagService:
    def __init__(self, llm_client: DashScopeClient) -> None:
        self.settings = get_settings()
        self.llm_client = llm_client

    def _query_terms(self, query: str) -> list[str]:
        terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", query)
        return terms[:6] if terms else [query.strip()[:32]]

    async def _keyword_search(self, db: AsyncSession, query: str, top_k: int) -> list[dict]:
        terms = self._query_terms(query)
        if not terms:
            return []
        clauses = [KnowledgeChunk.content.ilike(f"%{term}%") for term in terms]
        stmt = select(
            KnowledgeChunk.id,
            KnowledgeChunk.document_id,
            KnowledgeChunk.chunk_index,
            KnowledgeChunk.content,
        ).where(or_(*clauses)).limit(top_k)
        rows = (await db.execute(stmt)).all()
        results: list[dict] = []
        for rank, row in enumerate(rows):
            results.append(
                {
                    "chunk_id": str(row.id),
                    "document_id": str(row.document_id),
                    "chunk_index": row.chunk_index,
                    "content": row.content,
                    "score": round(1.0 / (60 + rank), 6),
                    "source": "keyword",
                }
            )
        return results

    async def _vector_search(self, db: AsyncSession, query: str, top_k: int) -> list[dict]:
        vectors = await self.llm_client.embedding([query])
        query_vector = vectors[0]
        distance_expr = KnowledgeChunk.embedding.cosine_distance(query_vector)
        stmt = (
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.document_id,
                KnowledgeChunk.chunk_index,
                KnowledgeChunk.content,
                distance_expr.label("distance"),
            )
            .order_by(distance_expr)
            .limit(top_k)
        )
        rows = (await db.execute(stmt)).all()
        results: list[dict] = []
        for row in rows:
            score = round(1 - float(row.distance), 6)
            results.append(
                {
                    "chunk_id": str(row.id),
                    "document_id": str(row.document_id),
                    "chunk_index": row.chunk_index,
                    "content": row.content,
                    "score": score,
                    "source": "vector",
                }
            )
        return results

    def _rrf_merge(self, keyword: list[dict], vector: list[dict], top_k: int, k: int = 60) -> list[dict]:
        scores: dict[str, float] = {}
        payload: dict[str, dict] = {}
        for rank, item in enumerate(keyword):
            cid = item["chunk_id"]
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            payload[cid] = item
        for rank, item in enumerate(vector):
            cid = item["chunk_id"]
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            payload[cid] = item
        ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        merged: list[dict] = []
        for cid, rrf in ordered:
            item = payload[cid].copy()
            item["score"] = round(rrf * 10, 6)
            item["source"] = "hybrid"
            merged.append(item)
        return merged

    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        top_k: int | None = None,
        session_id=None,
        message_id=None,
    ) -> list[dict]:
        use_top_k = top_k or self.settings.rag_top_k
        if self.settings.rag_hybrid_enabled:
            keyword_hits = await self._keyword_search(db, query, self.settings.rag_keyword_top_k)
            vector_hits = await self._vector_search(db, query, use_top_k)
            results = self._rrf_merge(keyword_hits, vector_hits, use_top_k)
        else:
            results = await self._vector_search(db, query, use_top_k)

        db.add(
            RetrievalLog(
                session_id=session_id,
                message_id=message_id,
                query=query,
                top_k=use_top_k,
                results={"items": results, "hybrid": self.settings.rag_hybrid_enabled},
            )
        )
        await db.flush()
        return results
