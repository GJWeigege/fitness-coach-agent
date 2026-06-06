import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class BenchmarkRunCreateRequest(BaseModel):
    dataset_name: str = Field(default="coach_eval", max_length=128)
    sample_limit: int | None = Field(default=None, ge=1, le=500)
    sample_ids: list[str] | None = Field(default=None, max_length=100)

    @field_validator("sample_ids")
    @classmethod
    def validate_sample_ids_non_empty(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) == 0:
            raise ValueError("sample_ids 不能为空")
        return value

    @model_validator(mode="after")
    def validate_subset_options(self) -> "BenchmarkRunCreateRequest":
        if self.sample_limit is not None and self.sample_ids:
            raise ValueError("sample_limit 与 sample_ids 不能同时指定")
        return self


class BenchmarkRunCancelResponse(BaseModel):
    id: uuid.UUID
    status: str


class FeedbackSyncRequest(BaseModel):
    include_down: bool = True
    include_up: bool = True
    merge_queue: bool = False
    dry_run: bool = False


class FeedbackSyncResponse(BaseModel):
    queue_added: int
    queue_skipped: int
    sft_added: int
    sft_skipped: int
    merged: int | None = None
    benchmark_path: str
    sft_path: str
    queue_path: str


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
    created_by_user_id: uuid.UUID
    created_by_username: str | None = None
    created_at: datetime | None = None
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
    created_by_user_id: uuid.UUID
    created_by_username: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None
    finished_at: datetime | None
    metrics: dict | None
    error_message: str | None
    results: list[BenchmarkResultItem]
