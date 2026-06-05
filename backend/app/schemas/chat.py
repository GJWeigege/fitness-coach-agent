import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class MessageItem(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    citations: list[dict] | None = None
    agent_run_id: uuid.UUID | None = None
    feedback: str | None = None


class MessageFeedbackRequest(BaseModel):
    rating: str = Field(pattern="^(up|down)$")


class SessionSummaryItem(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class SessionMessagesResponse(BaseModel):
    session_id: uuid.UUID
    messages: list[MessageItem]


class SessionListResponse(BaseModel):
    sessions: list[SessionSummaryItem]
