import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, ChatMessage, ChatSession
from app.services.benchmark_runner import BENCHMARK_SESSION_TITLE_PREFIX

RESERVED_BENCHMARK_TITLE_MESSAGE = "会话标题不能使用评测专用前缀。"


def reject_reserved_session_title(title: str | None) -> None:
    if title and title.startswith(BENCHMARK_SESSION_TITLE_PREFIX):
        raise HTTPException(status_code=400, detail=RESERVED_BENCHMARK_TITLE_MESSAGE)


class ChatSessionService:
    def _touch_session(self, session: ChatSession) -> None:
        session.updated_at = datetime.now(timezone.utc)

    async def delete_session_rows(self, db: AsyncSession, session_id: uuid.UUID) -> None:
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
        await db.execute(delete(AgentRun).where(AgentRun.session_id == session_id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session_id))

    async def create_session(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        title: str | None = None,
    ) -> ChatSession:
        reject_reserved_session_title(title)
        session = ChatSession(user_id=user_id, title=title)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def list_sessions(self, db: AsyncSession, user_id: uuid.UUID | None = None) -> list[ChatSession]:
        stmt = select(ChatSession).order_by(ChatSession.updated_at.desc())
        if user_id is not None:
            stmt = stmt.where(ChatSession.user_id == user_id)
        stmt = stmt.where(
            or_(
                ChatSession.title.is_(None),
                ~ChatSession.title.startswith(BENCHMARK_SESSION_TITLE_PREFIX),
            )
        )
        return list((await db.scalars(stmt)).all())

    async def list_messages(self, db: AsyncSession, session_id: uuid.UUID) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        return list((await db.scalars(stmt)).all())

    async def rename_session(self, db: AsyncSession, session_id: uuid.UUID, title: str) -> ChatSession:
        session = await db.get(ChatSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在。")
        reject_reserved_session_title(title)
        session.title = title
        self._touch_session(session)
        await db.commit()
        await db.refresh(session)
        return session

    async def delete_session(self, db: AsyncSession, session_id: uuid.UUID) -> None:
        session = await db.get(ChatSession, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在。")
        await self.delete_session_rows(db, session_id)
        await db.commit()
