import pytest
from sqlalchemy import func, select

from app.auth.password import verify_password
from app.auth.permissions import get_permissions_for_role, list_roles, resolve_user_permissions
from app.db.models import User
from app.db.seed_users import DEMO_PASSWORD, DEMO_USERS, seed_demo_users


def test_demo_users_have_valid_roles():
    roles = set(list_roles())
    for spec in DEMO_USERS:
        assert spec.role in roles


def test_demo_usernames_are_unique():
    usernames = [spec.username for spec in DEMO_USERS]
    assert len(usernames) == len(set(usernames))


def test_demo_password_is_documented_constant():
    assert DEMO_PASSWORD == "Demo@123456"
    assert len(DEMO_PASSWORD) >= 8


def test_demo_user_specs_match_design():
    by_username = {spec.username: spec for spec in DEMO_USERS}
    assert set(by_username) == {"coach_demo", "admin_demo", "kb_demo"}
    assert by_username["coach_demo"].role == "user"
    assert by_username["admin_demo"].role == "admin"
    assert by_username["kb_demo"].role == "kb_editor"


def test_admin_demo_has_full_admin_permissions():
    spec = next(item for item in DEMO_USERS if item.username == "admin_demo")
    perms = resolve_user_permissions(spec.role, spec.custom_permissions)
    assert perms == get_permissions_for_role("admin")


def test_kb_demo_has_kb_editor_permissions():
    spec = next(item for item in DEMO_USERS if item.username == "kb_demo")
    perms = resolve_user_permissions(spec.role, spec.custom_permissions)
    assert "knowledge:write" in perms
    assert "knowledge:reindex" in perms
    assert "user:manage" not in perms


@pytest.mark.asyncio
async def test_seed_demo_users_creates_three_users(db_session):
    created = await seed_demo_users(db_session)
    assert len(created) == 3
    assert set(created) == {spec.username for spec in DEMO_USERS}

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 3

    for spec in DEMO_USERS:
        user = await db_session.scalar(select(User).where(User.username == spec.username))
        assert user is not None
        assert user.role == spec.role
        assert user.is_active is True
        assert verify_password(DEMO_PASSWORD, user.password_hash, user.password_salt)


@pytest.mark.asyncio
async def test_seed_demo_users_is_idempotent(db_session):
    first = await seed_demo_users(db_session)
    second = await seed_demo_users(db_session)
    assert len(first) == 3
    assert second == []

    count = await db_session.scalar(select(func.count()).select_from(User))
    assert count == 3
