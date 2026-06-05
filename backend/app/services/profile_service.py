import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TrainingLog, UserProfile
from app.schemas.profile import (
    TrainingLogCreate,
    TrainingLogItem,
    UserFitnessProfileResponse,
    UserFitnessProfileUpdate,
)


EXPERIENCE_LEVELS = {"beginner", "intermediate", "advanced"}


class ProfileService:
    def _empty_profile(self, user_id: uuid.UUID) -> UserFitnessProfileResponse:
        return UserFitnessProfileResponse(user_id=user_id)

    def _to_profile_response(self, profile: UserProfile) -> UserFitnessProfileResponse:
        return UserFitnessProfileResponse(
            user_id=profile.user_id,
            age=profile.age,
            sex=profile.sex,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            goals=profile.goals,
            experience_level=profile.experience_level,
            injuries=profile.injuries,
            equipment=profile.equipment,
            diet_preference=profile.diet_preference,
            updated_at=profile.updated_at,
        )

    async def get_profile(self, db: AsyncSession, user_id: uuid.UUID) -> UserFitnessProfileResponse:
        profile = await db.get(UserProfile, user_id)
        if profile is None:
            return self._empty_profile(user_id)
        return self._to_profile_response(profile)

    async def upsert_profile(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        payload: UserFitnessProfileUpdate,
    ) -> UserFitnessProfileResponse:
        if payload.experience_level is not None and payload.experience_level not in EXPERIENCE_LEVELS:
            raise ValueError(f"experience_level 必须是 {', '.join(sorted(EXPERIENCE_LEVELS))} 之一。")

        profile = await db.get(UserProfile, user_id)
        if profile is None:
            profile = UserProfile(user_id=user_id)
            db.add(profile)

        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(profile, key, value)
        profile.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return self._to_profile_response(profile)

    async def list_training_logs(self, db: AsyncSession, user_id: uuid.UUID) -> list[TrainingLogItem]:
        stmt = (
            select(TrainingLog)
            .where(TrainingLog.user_id == user_id)
            .order_by(TrainingLog.session_date.desc(), TrainingLog.created_at.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        return [
            TrainingLogItem(
                id=row.id,
                session_date=row.session_date,
                activity_type=row.activity_type,
                duration_min=row.duration_min,
                intensity=row.intensity,
                notes=row.notes,
                created_at=row.created_at,
            )
            for row in rows
        ]

    async def create_training_log(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        payload: TrainingLogCreate,
    ) -> TrainingLogItem:
        row = TrainingLog(
            user_id=user_id,
            session_date=payload.session_date,
            activity_type=payload.activity_type,
            duration_min=payload.duration_min,
            intensity=payload.intensity,
            notes=payload.notes,
        )
        db.add(row)
        await db.flush()
        return TrainingLogItem(
            id=row.id,
            session_date=row.session_date,
            activity_type=row.activity_type,
            duration_min=row.duration_min,
            intensity=row.intensity,
            notes=row.notes,
            created_at=row.created_at,
        )
