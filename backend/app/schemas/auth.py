import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    role: str = "user"
    custom_permissions: list[str] | None = None


class UpdateUserRequest(BaseModel):
    role: str | None = None
    custom_permissions: list[str] | None = None
    is_active: bool | None = None


class UserProfile(BaseModel):
    id: uuid.UUID
    username: str
    role: str
    permissions: list[str]
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


class UserListResponse(BaseModel):
    users: list[UserProfile]


class PermissionMatrixResponse(BaseModel):
    roles: dict[str, list[str]]
