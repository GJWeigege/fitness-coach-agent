import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, get_db, get_user_permissions
from app.core.rate_limit import CHAT_WRITE_RATE, enforce_rate_limit, enforce_user_rate_limit
from app.db.models import ChatMessage, ChatSession, User
from app.schemas.chat import (
    CreateSessionRequest,
    MessageFeedbackRequest,
    MessageItem,
    RenameSessionRequest,
    SessionListResponse,
    SessionMessagesResponse,
    SessionSummaryItem,
)
from app.services.chat_session_service import ChatSessionService

router = APIRouter(prefix="/chat", tags=["chat"])
service = ChatSessionService()


def _enforce_chat_write_rate_limit(http_request: Request, user: User) -> None:
    enforce_rate_limit(http_request, CHAT_WRITE_RATE, scope="chat_write")
    enforce_user_rate_limit(str(user.id), CHAT_WRITE_RATE, scope="chat_write")


def _require_session_read(session: ChatSession, user: User, permissions: set[str]) -> None:
    if "session:read:all" in permissions:
        return
    if "session:read:own" not in permissions:
        raise HTTPException(status_code=403, detail="无权读取会话。")
    if session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问其他用户会话。")


def _require_session_manage(session: ChatSession, user: User, permissions: set[str]) -> None:
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
    sessions = await service.list_sessions(db=db, user_id=filter_user)
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
    created = await service.create_session(db=db, user_id=user.id, title=title)
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
    updated = await service.rename_session(db=db, session_id=session_id, title=request.title)
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
    await service.delete_session(db=db, session_id=session_id)
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
    messages = await service.list_messages(db=db, session_id=session_id)
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
    if "session:read:all" not in permissions and session.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权反馈该消息。")
    if record.role != "assistant":
        raise HTTPException(status_code=400, detail="只能对教练回复进行评价。")
    _enforce_chat_write_rate_limit(http_request, user)
    record.feedback = request.rating
    await db.commit()
    return {"ok": True, "message_id": str(message_id), "rating": request.rating}
