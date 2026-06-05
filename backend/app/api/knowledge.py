import logging
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import get_db, require_permissions
from app.core.errors import PUBLIC_ERROR_MESSAGE
from app.core.rate_limit import REINDEX_RATE, UPLOAD_RATE, enforce_rate_limit, enforce_user_rate_limit
from app.db.models import KnowledgeChunk, KnowledgeDocument, User
from app.llm.dashscope_client import DashScopeClient
from app.schemas.knowledge import KnowledgeDocumentItem, KnowledgeDocumentListResponse, KnowledgeUploadResponse
from app.services.ingest_service import IngestService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge(
    http_request: Request,
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

    try:
        service = IngestService(llm_client=DashScopeClient())
    except ValueError as exc:
        logger.exception("ingest_client_init_failed")
        raise HTTPException(status_code=500, detail=PUBLIC_ERROR_MESSAGE) from exc
    try:
        doc, chunk_count = await service.ingest_file(db=db, file_path=target, title=file.filename)
    except ValueError as exc:
        logger.warning("knowledge_upload_rejected: %s", exc)
        raise HTTPException(status_code=400, detail="文件内容无法处理，请检查格式后重试。") from exc

    await db.commit()
    return KnowledgeUploadResponse(document_id=doc.id, chunks=chunk_count, title=doc.title)


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


@router.post("/documents/{document_id}/reindex", response_model=KnowledgeUploadResponse)
async def reindex_document(
    document_id: UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("knowledge:reindex")),
) -> KnowledgeUploadResponse:
    enforce_rate_limit(http_request, REINDEX_RATE, scope="knowledge_reindex")
    enforce_user_rate_limit(str(user.id), REINDEX_RATE, scope="knowledge_reindex")
    try:
        service = IngestService(llm_client=DashScopeClient())
    except ValueError as exc:
        logger.exception("reindex_client_init_failed")
        raise HTTPException(status_code=500, detail=PUBLIC_ERROR_MESSAGE) from exc
    try:
        doc, count = await service.reindex_document(db=db, document_id=document_id)
    except ValueError as exc:
        logger.warning("knowledge_reindex_rejected doc=%s: %s", document_id, exc)
        raise HTTPException(status_code=400, detail="文档无法重新索引，请确认文件仍存在且格式有效。") from exc
    await db.commit()
    return KnowledgeUploadResponse(document_id=doc.id, chunks=count, title=doc.title)
