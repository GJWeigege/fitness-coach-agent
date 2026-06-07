import uuid
from datetime import datetime

from pydantic import BaseModel, Field, ValidationError


class ChatSendRequest(BaseModel):
    session_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=8000)
    use_rag: bool = True


class ChatSendResponse(BaseModel):
    session_id: uuid.UUID
    reply: str
    citations: list[dict]
    model_name: str
    run_id: uuid.UUID | None = None
    status: str | None = None


class CreateSessionRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class RenameSessionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class MessageStepItem(BaseModel):
    phase: str
    summary: str
    step_index: int | None = None
    detail: dict | None = None


def parse_message_step_items(raw_steps: list | None) -> list[MessageStepItem]:
    """Parse persisted step rows; skip malformed entries instead of raising."""
    if not isinstance(raw_steps, list):
        return []
    items: list[MessageStepItem] = []
    for step in raw_steps:
        if not isinstance(step, dict):
            continue
        try:
            items.append(MessageStepItem.model_validate(step))
        except ValidationError:
            continue
    return items


class MessageItem(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    citations: list[dict] | None = None
    agent_run_id: uuid.UUID | None = None
    feedback: str | None = None
    steps: list[MessageStepItem] | None = None
    run_status: str | None = None
    step_count: int | None = None
    latency_ms: int | None = None
    intent: str | None = None


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
