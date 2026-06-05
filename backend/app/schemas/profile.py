import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class UserFitnessProfileResponse(BaseModel):
    user_id: uuid.UUID
    age: int | None = None
    sex: str | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    goals: list[str] | None = None
    experience_level: str = "beginner"
    injuries: list[str] | None = None
    equipment: list[str] | None = None
    diet_preference: str | None = None
    updated_at: datetime | None = None


class UserFitnessProfileUpdate(BaseModel):
    age: int | None = None
    sex: str | None = None
    height_cm: float | None = None
    weight_kg: float | None = None
    goals: list[str] | None = None
    experience_level: str | None = None
    injuries: list[str] | None = None
    equipment: list[str] | None = None
    diet_preference: str | None = None


class TrainingLogItem(BaseModel):
    id: uuid.UUID
    session_date: date
    activity_type: str
    duration_min: int
    intensity: str
    notes: str | None = None
    created_at: datetime


class TrainingLogCreate(BaseModel):
    session_date: date
    activity_type: str = Field(min_length=1, max_length=64)
    duration_min: int = Field(ge=1)
    intensity: str = Field(min_length=1, max_length=32)
    notes: str | None = None


class TrainingLogListResponse(BaseModel):
    logs: list[TrainingLogItem]
