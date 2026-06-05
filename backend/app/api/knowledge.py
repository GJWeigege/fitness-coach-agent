import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_db, require_permissions
from app.core.errors import PUBLIC_ERROR_MESSAGE
from app.core.rate_limit import REINDEX_RATE, UPLOAD_RATE, enforce_rate_limit, enforce_user_rate_limit
from app.db.models import KnowledgeChunk, KnowledgeDocument, User
from app.db.session import AsyncSessionLocal
from app.llm.dashscope_client import DashScopeClient
from app.schemas.knowledge import KnowledgeDocumentItem, KnowledgeDocumentListResponse, KnowledgeUploadResponse
from app.services.ingest_service import IngestService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


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
    source_path = Path(doc.source_path)
    if not source_path.exists():
        raise HTTPException(status_code=400, detail="源文件不存在，无法重建索引。")

    doc.status = "reindexing"
    await db.commit()

    background_tasks.add_task(_reindex_background, document_id)
    return KnowledgeUploadResponse(document_id=doc.id, chunks=0, title=doc.title, status=doc.status)
