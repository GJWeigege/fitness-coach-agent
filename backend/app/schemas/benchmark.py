import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BenchmarkRunCreateRequest(BaseModel):
    dataset_name: str = Field(default="coach_eval", max_length=128)


class BenchmarkRunCreateResponse(BaseModel):
    id: uuid.UUID
    dataset_name: str
    status: str


class BenchmarkResultItem(BaseModel):
    id: uuid.UUID
    sample_id: str
    question: str
    expected_intent: str
    predicted_intent: str | None
    passed: bool
    metrics: dict | None
    agent_run_id: uuid.UUID | None


class BenchmarkRunListItem(BaseModel):
    id: uuid.UUID
    dataset_name: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    metrics: dict | None
    error_message: str | None


class BenchmarkRunListResponse(BaseModel):
    runs: list[BenchmarkRunListItem]
    total: int


class BenchmarkRunDetailResponse(BaseModel):
    id: uuid.UUID
    dataset_name: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    metrics: dict | None
    error_message: str | None
    results: list[BenchmarkResultItem]
