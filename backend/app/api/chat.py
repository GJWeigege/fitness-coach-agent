import logging
import uuid
from functools import lru_cache
from json import dumps

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_user_permissions, require_permissions
from app.core.errors import PUBLIC_ERROR_MESSAGE
from app.core.rate_limit import CHAT_WRITE_RATE, STREAM_RATE, enforce_rate_limit, enforce_user_rate_limit
from app.db.models import ChatMessage, ChatSession, User
from app.db.session import AsyncSessionLocal
from app.llm.dashscope_client import DashScopeClient
from app.schemas.chat import (
    ChatSendRequest,
    ChatSendResponse,
    CreateSessionRequest,
    MessageFeedbackRequest,
    MessageItem,
    RenameSessionRequest,
    SessionListResponse,
    SessionMessagesResponse,
    SessionSummaryItem,
)
from app.services.chat_service import ChatService
from app.services.chat_session_service import ChatSessionService
from app.services.benchmark_runner import is_benchmark_chat_session
from app.services.rag_service import RagService

router = APIRouter(prefix="/chat", tags=["chat"])
session_service = ChatSessionService()
logger = logging.getLogger(__name__)


@lru_cache
def get_chat_service() -> ChatService:
    llm_client = DashScopeClient()
    rag_service = RagService(llm_client=llm_client)
    return ChatService(llm_client=llm_client, rag_service=rag_service)


def _require_chat_service() -> ChatService:
    try:
        return get_chat_service()
    except ValueError as exc:
        logger.exception("chat_service_init_failed")
        raise HTTPException(status_code=500, detail=PUBLIC_ERROR_MESSAGE) from exc


def _enforce_chat_write_rate_limit(http_request: Request, user: User) -> None:
    enforce_rate_limit(http_request, CHAT_WRITE_RATE, scope="chat_write")
    enforce_user_rate_limit(str(user.id), CHAT_WRITE_RATE, scope="chat_write")


def _enforce_chat_stream_rate_limit(http_request: Request, user: User) -> None:
    enforce_rate_limit(http_request, STREAM_RATE, scope="chat_stream")
    enforce_user_rate_limit(str(user.id), STREAM_RATE, scope="chat_stream")


def _reject_benchmark_session(session: ChatSession) -> None:
    if is_benchmark_chat_session(session):
        raise HTTPException(status_code=403, detail="评测会话请在 Benchmark 页面查看。")


def _require_session_read(session: ChatSession, user: User, permissions: set[str]) -> None:
    _reject_benchmark_session(session)
    if "session:read:all" in permissions:
        return
    if "session:read:own" not in permissions:
        raise HTTPException(status_code=403, detail="无权读取会话。")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问其他用户会话。")


def _require_session_manage(session: ChatSession, user: User, permissions: set[str]) -> None:
    _reject_benchmark_session(session)
    if "session:manage:all" in permissions:
        return
    if "session:manage:own" not in permissions:
        raise HTTPException(status_code=403, detail="无权管理会话。")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权操作该会话。")


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    user_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionListResponse:
    permissions = get_user_permissions(user)
    if "session:read:all" not in permissions and "session:read:own" not in permissions:
        raise HTTPException(status_code=403, detail="无权读取会话。")
    filter_user = user_id
    if "session:read:all" not in permissions:
        filter_user = user.id
    sessions = await session_service.list_sessions(db=db, user_id=filter_user)
    return SessionListResponse(
        sessions=[
            SessionSummaryItem(
                id=s.id,
                user_id=s.user_id,
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ]
    )


@router.post("/sessions", response_model=SessionSummaryItem)
async def create_session(
    http_request: Request,
    request: CreateSessionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionSummaryItem:
    permissions = get_user_permissions(user)
    if "session:manage:own" not in permissions and "session:manage:all" not in permissions:
        raise HTTPException(status_code=403, detail="无权管理会话。")
    _enforce_chat_write_rate_limit(http_request, user)
    title = request.title if request is not None else None
    created = await session_service.create_session(db=db, user_id=user.id, title=title)
    return SessionSummaryItem(
        id=created.id,
        user_id=created.user_id,
        title=created.title,
        created_at=created.created_at,
        updated_at=created.updated_at,
    )


@router.patch("/sessions/{session_id}", response_model=SessionSummaryItem)
async def rename_session(
    session_id: uuid.UUID,
    request: RenameSessionRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionSummaryItem:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    permissions = get_user_permissions(user)
    _require_session_manage(session, user, permissions)
    _enforce_chat_write_rate_limit(http_request, user)
    updated = await session_service.rename_session(db=db, session_id=session_id, title=request.title)
    return SessionSummaryItem(
        id=updated.id,
        user_id=updated.user_id,
        title=updated.title,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: uuid.UUID,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    permissions = get_user_permissions(user)
    _require_session_manage(session, user, permissions)
    _enforce_chat_write_rate_limit(http_request, user)
    await session_service.delete_session(db=db, session_id=session_id)
    return {"ok": True}


@router.get("/sessions/{session_id}/messages", response_model=SessionMessagesResponse)
async def list_session_messages(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SessionMessagesResponse:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    permissions = get_user_permissions(user)
    _require_session_read(session, user, permissions)
    messages = await session_service.list_messages(db=db, session_id=session_id)
    items: list[MessageItem] = []
    for item in messages:
        citations = None
        if item.retrieved_chunks and isinstance(item.retrieved_chunks, dict):
            citations = item.retrieved_chunks.get("items")
        items.append(
            MessageItem(
                id=item.id,
                role=item.role,
                content=item.content,
                created_at=item.created_at,
                citations=citations,
                agent_run_id=item.agent_run_id,
                feedback=item.feedback,
            )
        )
    return SessionMessagesResponse(session_id=session_id, messages=items)


@router.post("/send", response_model=ChatSendResponse)
async def send_chat(
    request: ChatSendRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("chat:send")),
) -> ChatSendResponse:
    _enforce_chat_stream_rate_limit(http_request, user)
    if request.session_id is not None:
        session = await db.get(ChatSession, request.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在。")
        _reject_benchmark_session(session)
    service = _require_chat_service()
    result = await service.send_message(
        db=db,
        user_message=request.message,
        session_id=request.session_id,
        user_id=user.id,
        use_rag=request.use_rag,
    )
    return ChatSendResponse(**result)


@router.post("/stream")
async def stream_chat(
    request: ChatSendRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("chat:send")),
):
    _enforce_chat_stream_rate_limit(http_request, user)
    if request.session_id is not None:
        session = await db.get(ChatSession, request.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在。")
        _reject_benchmark_session(session)
    service = _require_chat_service()

    async def event_generator():
        async with AsyncSessionLocal() as db:
            try:
                async for event in service.stream_message(
                    db=db,
                    user_message=request.message,
                    user_id=user.id,
                    session_id=request.session_id,
                    use_rag=request.use_rag,
                ):
                    yield f"data: {dumps(event, ensure_ascii=False)}\n\n"
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, str) else PUBLIC_ERROR_MESSAGE
                yield f"data: {dumps({'type': 'error', 'message': detail}, ensure_ascii=False)}\n\n"
            except Exception:
                logger.exception("stream_chat_failed user_id=%s", user.id)
                yield f"data: {dumps({'type': 'error', 'message': PUBLIC_ERROR_MESSAGE}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/messages/{message_id}/feedback")
async def message_feedback(
    message_id: uuid.UUID,
    request: MessageFeedbackRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    permissions = get_user_permissions(user)
    if "feedback:write" not in permissions:
        raise HTTPException(status_code=403, detail="权限不足，缺少: feedback:write")
    record = await db.get(ChatMessage, message_id)
    if record is None:
        raise HTTPException(status_code=404, detail="消息不存在。")
    session = await db.get(ChatSession, record.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在。")
    _reject_benchmark_session(session)
    if "session:read:all" not in permissions and session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权反馈该消息。")
    if record.role != "assistant":
        raise HTTPException(status_code=400, detail="只能对教练回复进行评价。")
    _enforce_chat_write_rate_limit(http_request, user)
    record.feedback = request.rating
    await db.commit()
    return {"ok": True, "message_id": str(message_id), "rating": request.rating}
