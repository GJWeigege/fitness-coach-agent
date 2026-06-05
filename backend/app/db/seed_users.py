from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.auth.permissions import get_permissions_for_role, validate_custom_permissions
from app.db.models import User

DEMO_PASSWORD = "Demo@123456"


@dataclass(frozen=True)
class DemoUserSpec:
    username: str
    role: str
    custom_permissions: list[str] | None = None


DEMO_USERS: tuple[DemoUserSpec, ...] = (
    DemoUserSpec(username="coach_demo", role="user"),
    DemoUserSpec(
        username="admin_demo",
        role="admin",
        custom_permissions=sorted(get_permissions_for_role("admin")),
    ),
    DemoUserSpec(username="kb_demo", role="kb_editor"),
)


async def seed_demo_users(db: AsyncSession) -> list[str]:
    """在 dev/test 环境写入演示账号；已存在的用户名会跳过。"""
    created: list[str] = []
    password_hash, password_salt = hash_password(DEMO_PASSWORD)

    for spec in DEMO_USERS:
        exists = await db.scalar(select(User.id).where(User.username == spec.username))
        if exists:
            continue

        custom_permissions = validate_custom_permissions(spec.custom_permissions)
        db.add(
            User(
                username=spec.username,
                password_hash=password_hash,
                password_salt=password_salt,
                role=spec.role,
                custom_permissions=custom_permissions,
                is_active=True,
            )
        )
        created.append(spec.username)

    if created:
        await db.flush()
    return created
