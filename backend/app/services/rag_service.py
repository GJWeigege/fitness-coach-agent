import logging
import math
import re
import uuid

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import KnowledgeChunk, RetrievalLog
from app.llm.dashscope_client import DashScopeClient

logger = logging.getLogger(__name__)


class RagService:
    def __init__(self, llm_client: DashScopeClient) -> None:
        self.settings = get_settings()
        self.llm_client = llm_client

    def _query_terms(self, query: str) -> list[str]:
        raw = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]{2,}", query)
        terms: list[str] = []
        for token in raw:
            if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
                for i in range(len(token) - 1):
                    bigram = token[i : i + 2]
                    if bigram not in terms:
                        terms.append(bigram)
            elif token not in terms:
                terms.append(token)
        if not terms and query.strip():
            terms = [query.strip()[:32]]
        return terms[:6]

    def _term_match_score(self, terms: list[str]):
        score = None
        for term in terms:
            escaped = self._escape_ilike_term(term)
            part = case((KnowledgeChunk.content.ilike(f"%{escaped}%", escape="\\"), 1), else_=0)
            score = part if score is None else score + part
        return score

    def _escape_ilike_term(self, term: str) -> str:
        return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    async def _keyword_search(self, db: AsyncSession, query: str, top_k: int) -> list[dict]:
        terms = self._query_terms(query)
        if not terms:
            return []
        clauses = [
            KnowledgeChunk.content.ilike(f"%{self._escape_ilike_term(term)}%", escape="\\")
            for term in terms
        ]
        match_score = self._term_match_score(terms)
        stmt = (
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.document_id,
                KnowledgeChunk.chunk_index,
                KnowledgeChunk.content,
                match_score.label("match_score"),
            )
            .where(or_(*clauses))
            .order_by(match_score.desc())
            .limit(top_k)
        )
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
                    "keyword_rank": rank,
                    "keyword_hit": True,
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
        for rank, row in enumerate(rows):
            vector_score = round(1 - float(row.distance), 6)
            results.append(
                {
                    "chunk_id": str(row.id),
                    "document_id": str(row.document_id),
                    "chunk_index": row.chunk_index,
                    "content": row.content,
                    "score": vector_score,
                    "vector_score": vector_score,
                    "vector_rank": rank,
                    "source": "vector",
                }
            )
        return results

    def _rrf_merge(self, keyword: list[dict], vector: list[dict], k: int = 60) -> list[dict]:
        scores: dict[str, float] = {}
        payload: dict[str, dict] = {}
        vector_scores: dict[str, float] = {}
        keyword_ranks: dict[str, int] = {}
        vector_ranks: dict[str, int] = {}
        keyword_hits: set[str] = set()

        for rank, item in enumerate(keyword):
            cid = item["chunk_id"]
            keyword_hits.add(cid)
            keyword_ranks[cid] = rank
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            payload[cid] = item

        for rank, item in enumerate(vector):
            cid = item["chunk_id"]
            vector_scores[cid] = item["vector_score"]
            vector_ranks[cid] = rank
            scores[cid] = scores.get(cid, 0) + 1.0 / (k + rank + 1)
            if cid not in payload:
                payload[cid] = item
            else:
                payload[cid] = {**payload[cid], **item}

        ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        merged: list[dict] = []
        for cid, rrf in ordered:
            item = payload[cid].copy()
            item["score"] = round(rrf * 10, 6)
            item["vector_score"] = vector_scores.get(cid, 0.0)
            item["keyword_hit"] = cid in keyword_hits
            if cid in keyword_ranks:
                item["keyword_rank"] = keyword_ranks[cid]
            if cid in vector_ranks:
                item["vector_rank"] = vector_ranks[cid]
            item["source"] = "hybrid"
            merged.append(item)
        return merged

    def _passes_quality_filter(
        self,
        item: dict,
        *,
        keyword_top_ids: set[str],
        vector_top_ids: set[str],
    ) -> bool:
        settings = self.settings
        vector_score = float(item.get("vector_score", 0))
        chunk_id = item["chunk_id"]

        if vector_score >= settings.rag_vector_score_min:
            return True
        if item.get("keyword_hit") and vector_score >= settings.rag_vector_score_min_with_keyword:
            return True
        if chunk_id in keyword_top_ids and chunk_id in vector_top_ids:
            return True
        if chunk_id in keyword_top_ids and item.get("keyword_hit"):
            return True
        return False

    def _filter_results(
        self,
        results: list[dict],
        *,
        keyword_top_ids: set[str],
        vector_top_ids: set[str],
    ) -> list[dict]:
        return [
            item
            for item in results
            if self._passes_quality_filter(
                item,
                keyword_top_ids=keyword_top_ids,
                vector_top_ids=vector_top_ids,
            )
        ]

    def _apply_per_document_limit(self, results: list[dict]) -> list[dict]:
        max_per_doc = self.settings.rag_max_chunks_per_document
        doc_counts: dict[str, int] = {}
        doc_indices: dict[str, set[int]] = {}
        limited: list[dict] = []
        for item in results:
            doc_id = item["document_id"]
            idx = item["chunk_index"]
            if doc_counts.get(doc_id, 0) >= max_per_doc:
                continue
            indices = doc_indices.setdefault(doc_id, set())
            if any(abs(idx - existing) <= 1 for existing in indices):
                continue
            indices.add(idx)
            doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1
            limited.append(item)
        return limited

    async def _load_chunk_embeddings(
        self,
        db: AsyncSession,
        chunk_ids: list[str],
    ) -> dict[str, list[float]]:
        if not chunk_ids:
            return {}
        uuid_ids = [uuid.UUID(chunk_id) for chunk_id in chunk_ids]
        stmt = select(KnowledgeChunk.id, KnowledgeChunk.embedding).where(
            KnowledgeChunk.id.in_(uuid_ids)
        )
        rows = (await db.execute(stmt)).all()
        return {str(row.id): list(row.embedding) for row in rows}

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right, strict=False))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    def _relevance_score(self, item: dict) -> float:
        if item.get("rerank_score") is not None:
            return float(item["rerank_score"])
        if item.get("vector_score") is not None:
            return float(item["vector_score"])
        return float(item.get("score", 0))

    def _mmr_select(
        self,
        candidates: list[dict],
        embeddings: dict[str, list[float]],
        top_k: int,
    ) -> list[dict]:
        if not candidates:
            return []

        lambda_mult = self.settings.rag_mmr_lambda
        selected: list[dict] = []
        remaining = list(candidates)

        while remaining and len(selected) < top_k:
            best_item: dict | None = None
            best_score = float("-inf")
            for item in remaining:
                relevance = self._relevance_score(item)
                chunk_id = item["chunk_id"]
                embedding = embeddings.get(chunk_id)
                if not selected or not embedding:
                    mmr_score = relevance
                else:
                    similarities = [
                        self._cosine_similarity(embedding, embeddings[chosen["chunk_id"]])
                        for chosen in selected
                        if embeddings.get(chosen["chunk_id"])
                    ]
                    max_similarity = max(similarities) if similarities else 0.0
                    mmr_score = lambda_mult * relevance - (1 - lambda_mult) * max_similarity
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_item = item
            if best_item is None:
                break
            selected.append(best_item)
            remaining.remove(best_item)
        return selected

    async def _apply_rerank(self, query: str, results: list[dict]) -> list[dict]:
        if not results:
            return results
        documents = [item["content"] for item in results]
        try:
            ranked = await self.llm_client.rerank(
                query,
                documents,
                top_n=len(documents),
            )
        except Exception:
            logger.warning("RAG rerank failed; falling back to hybrid ordering", exc_info=True)
            return results

        reordered: list[dict] = []
        seen_indices: set[int] = set()
        for item in ranked:
            index = item["index"]
            if index < 0 or index >= len(results):
                continue
            seen_indices.add(index)
            source = results[index].copy()
            source["rerank_score"] = round(item["relevance_score"], 6)
            source["score"] = source["rerank_score"]
            reordered.append(source)
        if not reordered:
            logger.warning("RAG rerank returned no valid results; falling back to hybrid ordering")
            return results
        if len(reordered) < len(results):
            logger.warning(
                "RAG rerank returned partial results (%d/%d); appending unranked candidates",
                len(reordered),
                len(results),
            )
            for index, candidate in enumerate(results):
                if index in seen_indices:
                    continue
                reordered.append(candidate)
        return reordered

    async def _finalize_results(
        self,
        db: AsyncSession,
        query: str,
        results: list[dict],
        top_k: int,
    ) -> list[dict]:
        if not results:
            return []

        candidate_limit = self.settings.rag_rerank_candidate_k
        candidates = results[:candidate_limit]

        if self.settings.rag_rerank_enabled and len(candidates) > 1:
            candidates = await self._apply_rerank(query, candidates)

        if self.settings.rag_mmr_enabled and len(candidates) > top_k:
            embeddings = await self._load_chunk_embeddings(
                db,
                [item["chunk_id"] for item in candidates],
            )
            candidates = self._mmr_select(candidates, embeddings, top_k)
        else:
            candidates = candidates[:top_k]

        return self._apply_per_document_limit(candidates)[:top_k]

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
            vector_hits = await self._vector_search(db, query, self.settings.rag_vector_candidate_k)
            merged = self._rrf_merge(keyword_hits, vector_hits)
            keyword_top_ids = {
                hit["chunk_id"] for hit in keyword_hits[: self.settings.rag_keyword_top_for_filter]
            }
            vector_top_ids = {
                hit["chunk_id"] for hit in vector_hits[: self.settings.rag_vector_top_for_filter]
            }
            filtered = self._filter_results(
                merged,
                keyword_top_ids=keyword_top_ids,
                vector_top_ids=vector_top_ids,
            )
            results = await self._finalize_results(db, query, filtered, use_top_k)
        else:
            vector_hits = await self._vector_search(db, query, self.settings.rag_vector_candidate_k)
            filtered = [
                item
                for item in vector_hits
                if item["vector_score"] >= self.settings.rag_vector_score_min
            ]
            results = await self._finalize_results(db, query, filtered, use_top_k)

        db.add(
            RetrievalLog(
                session_id=session_id,
                message_id=message_id,
                query=query,
                top_k=use_top_k,
                results={
                    "items": results,
                    "hybrid": self.settings.rag_hybrid_enabled,
                    "rerank": self.settings.rag_rerank_enabled,
                    "mmr": self.settings.rag_mmr_enabled,
                },
            )
        )
        await db.flush()
        return results
