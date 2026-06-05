from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, require_permissions
from app.db.models import User
from app.schemas.profile import (
    TrainingLogCreate,
    TrainingLogItem,
    TrainingLogListResponse,
    UserFitnessProfileResponse,
    UserFitnessProfileUpdate,
)
from app.services.profile_service import ProfileService

router = APIRouter(prefix="/profile", tags=["profile"])
service = ProfileService()


@router.get("", response_model=UserFitnessProfileResponse)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("profile:read")),
) -> UserFitnessProfileResponse:
    return await service.get_profile(db=db, user_id=user.id)


@router.put("", response_model=UserFitnessProfileResponse)
async def update_profile(
    payload: UserFitnessProfileUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("profile:write")),
) -> UserFitnessProfileResponse:
    try:
        profile = await service.upsert_profile(db=db, user_id=user.id, payload=payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await db.commit()
    return profile


@router.get("/training-logs", response_model=TrainingLogListResponse)
async def list_training_logs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("profile:read")),
) -> TrainingLogListResponse:
    logs = await service.list_training_logs(db=db, user_id=user.id)
    return TrainingLogListResponse(logs=logs)


@router.post("/training-logs", response_model=TrainingLogItem)
async def create_training_log(
    payload: TrainingLogCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permissions("profile:write")),
) -> TrainingLogItem:
    log = await service.create_training_log(db=db, user_id=user.id, payload=payload)
    await db.commit()
    return log
