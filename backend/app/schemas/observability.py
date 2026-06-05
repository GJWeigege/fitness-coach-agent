import uuid
from datetime import datetime

from pydantic import BaseModel


class AgentStepItem(BaseModel):
    id: uuid.UUID
    step_index: int
    phase: str
    summary: str | None
    payload: dict | None
    duration_ms: int | None
    status: str
    created_at: datetime


class AgentRunListItem(BaseModel):
    id: uuid.UUID
    trace_id: str
    session_id: uuid.UUID
    intent: str | None
    status: str
    step_count: int
    total_latency_ms: int | None
    model_name: str | None
    memory_summary_updated: bool
    created_at: datetime
    finished_at: datetime | None


class AgentRunListResponse(BaseModel):
    runs: list[AgentRunListItem]
    total: int


class AgentRunDetailResponse(BaseModel):
    id: uuid.UUID
    trace_id: str
    session_id: uuid.UUID
    user_message_id: uuid.UUID | None
    assistant_message_id: uuid.UUID | None
    intent: str | None
    status: str
    step_count: int
    total_latency_ms: int | None
    error_message: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    model_name: str | None
    memory_compacted: bool
    dropped_message_count: int
    memory_summary_updated: bool
    created_at: datetime
    finished_at: datetime | None
    timeline: list[AgentStepItem]
