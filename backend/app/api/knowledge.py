import asyncio
import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_db, require_permissions
from app.core.errors import PUBLIC_ERROR_MESSAGE
from app.core.rate_limit import (
    REINDEX_ALL_RATE,
    REINDEX_RATE,
    UPLOAD_RATE,
    enforce_rate_limit,
    enforce_user_rate_limit,
)
from app.db.models import KnowledgeChunk, KnowledgeDocument, User
from app.db.session import AsyncSessionLocal
from app.llm.dashscope_client import DashScopeClient
from app.schemas.knowledge import (
    KnowledgeDocumentItem,
    KnowledgeDocumentListResponse,
    KnowledgeReindexAllResponse,
    KnowledgeReindexSkippedItem,
    KnowledgeUploadResponse,
)
from app.services.ingest_service import IngestService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)

_REINDEXABLE_STATUSES = frozenset({"indexed", "failed"})
# Process-local only; multi-worker deployments need a distributed lock (see docs/guide/05-RAG与Graph-RAG.md).
_reindex_all_lock = asyncio.Lock()


def _reindex_block_reason(doc: KnowledgeDocument, source_path: Path) -> str | None:
    if not source_path.exists():
        return "源文件不存在，无法重建索引。"
    if doc.status == "pending":
        return "文档正在入库，请稍后再试。"
    if doc.status == "reindexing":
        return "文档正在重建索引。"
    if doc.status not in _REINDEXABLE_STATUSES:
        return f"当前状态「{doc.status}」无法重建索引。"
    return None


async def _ingest_upload_background(document_id: UUID, file_path: Path) -> None:
    async with AsyncSessionLocal() as db:
        try:
            service = IngestService(llm_client=DashScopeClient())
            await service.ingest_pending_document(db, document_id, file_path)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("knowledge_upload_background_failed doc=%s", document_id)
            async with AsyncSessionLocal() as fail_db:
                doc = await fail_db.get(KnowledgeDocument, document_id)
                if doc is not None:
                    doc.status = "failed"
                    await fail_db.commit()


async def _reindex_all_background(document_ids: list[UUID]) -> None:
    async with _reindex_all_lock:
        for document_id in document_ids:
            await _reindex_background(document_id)


async def _reindex_background(document_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        try:
            service = IngestService(llm_client=DashScopeClient())
            await service.reindex_document(db, document_id=document_id)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("knowledge_reindex_background_failed doc=%s", document_id)
            async with AsyncSessionLocal() as fail_db:
                doc = await fail_db.get(KnowledgeDocument, document_id)
                if doc is not None:
                    doc.status = "failed"
                    await fail_db.commit()


@router.post("/upload", status_code=202, response_model=KnowledgeUploadResponse)
async def upload_knowledge(
    http_request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("knowledge:write")),
) -> KnowledgeUploadResponse:
    enforce_rate_limit(http_request, UPLOAD_RATE, scope="knowledge_upload")
    enforce_user_rate_limit(str(user.id), UPLOAD_RATE, scope="knowledge_upload")
    settings = get_settings()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".txt", ".md", ".pdf"}:
        raise HTTPException(status_code=400, detail="仅支持 txt/md/pdf 文件。")

    target = upload_dir / f"{uuid4().hex}{suffix}"
    max_bytes = settings.max_upload_bytes
    payload = await file.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过大小限制（{max_bytes // (1024 * 1024)}MB）。",
        )
    target.write_bytes(payload)

    doc = KnowledgeDocument(
        title=file.filename or target.name,
        source_path=str(target),
        content_hash="",
        status="pending",
    )
    db.add(doc)
    await db.commit()

    background_tasks.add_task(_ingest_upload_background, doc.id, target)
    return KnowledgeUploadResponse(document_id=doc.id, chunks=0, title=doc.title, status=doc.status)


@router.get("/documents", response_model=KnowledgeDocumentListResponse)
async def list_documents(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permissions("knowledge:read")),
) -> KnowledgeDocumentListResponse:
    stmt = (
        select(
            KnowledgeDocument.id,
            KnowledgeDocument.title,
            KnowledgeDocument.status,
            KnowledgeDocument.created_at,
            KnowledgeDocument.updated_at,
            func.count(KnowledgeChunk.id).label("chunk_count"),
        )
        .outerjoin(KnowledgeChunk, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .group_by(KnowledgeDocument.id)
        .order_by(KnowledgeDocument.updated_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return KnowledgeDocumentListResponse(
        documents=[
            KnowledgeDocumentItem(
                id=row.id,
                title=row.title,
                status=row.status,
                created_at=row.created_at,
                updated_at=row.updated_at,
                chunk_count=row.chunk_count,
            )
            for row in rows
        ]
    )


@router.post("/documents/{document_id}/reindex", status_code=202, response_model=KnowledgeUploadResponse)
async def reindex_document(
    document_id: UUID,
    http_request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("knowledge:reindex")),
) -> KnowledgeUploadResponse:
    enforce_rate_limit(http_request, REINDEX_RATE, scope="knowledge_reindex")
    enforce_user_rate_limit(str(user.id), REINDEX_RATE, scope="knowledge_reindex")

    doc = await db.get(KnowledgeDocument, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    if _reindex_all_lock.locked():
        raise HTTPException(status_code=409, detail="全量重建索引任务正在进行中，请稍后再试。")

    source_path = Path(doc.source_path)
    block_reason = _reindex_block_reason(doc, source_path)
    if block_reason is not None:
        status_code = 409 if doc.status == "reindexing" else 400
        raise HTTPException(status_code=status_code, detail=block_reason)

    doc.status = "reindexing"
    await db.commit()

    background_tasks.add_task(_reindex_background, document_id)
    return KnowledgeUploadResponse(document_id=doc.id, chunks=0, title=doc.title, status=doc.status)


@router.post("/reindex-all", status_code=202, response_model=KnowledgeReindexAllResponse)
async def reindex_all_documents(
    http_request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("knowledge:reindex")),
) -> KnowledgeReindexAllResponse:
    enforce_rate_limit(http_request, REINDEX_ALL_RATE, scope="knowledge_reindex_all")
    enforce_user_rate_limit(str(user.id), REINDEX_ALL_RATE, scope="knowledge_reindex_all")

    if _reindex_all_lock.locked():
        raise HTTPException(status_code=409, detail="全量重建索引任务正在进行中，请稍后再试。")

    docs = (await db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.asc()))).all()
    queued_ids: list[UUID] = []
    skipped: list[KnowledgeReindexSkippedItem] = []

    for doc in docs:
        source_path = Path(doc.source_path)
        block_reason = _reindex_block_reason(doc, source_path)
        if block_reason is not None:
            skipped.append(
                KnowledgeReindexSkippedItem(
                    document_id=doc.id,
                    title=doc.title,
                    reason=block_reason,
                )
            )
            continue
        doc.status = "reindexing"
        queued_ids.append(doc.id)

    await db.commit()

    if queued_ids:
        background_tasks.add_task(_reindex_all_background, queued_ids)

    return KnowledgeReindexAllResponse(queued_count=len(queued_ids), skipped=skipped)
