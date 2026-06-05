import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password, verify_password
from app.auth.permissions import (
    ROLE_PERMISSIONS,
    get_permissions_for_role,
    list_roles,
    resolve_user_permissions,
    validate_custom_permissions,
)
from app.auth.tokens import create_access_token
from app.core.config import get_settings
from app.core.deps import get_current_user, get_db, require_permissions
from app.core.login_lockout import login_lockout
from app.core.rate_limit import BOOTSTRAP_RATE, LOGIN_RATE, REGISTER_RATE, enforce_rate_limit
from app.db.models import User
from app.schemas.auth import (
    CreateUserRequest,
    LoginRequest,
    PermissionMatrixResponse,
    RegisterRequest,
    TokenResponse,
    UpdateUserRequest,
    UserListResponse,
    UserProfile,
)


router = APIRouter(prefix="/auth", tags=["auth"])


def to_user_profile(user: User) -> UserProfile:
    return UserProfile(
        id=user.id,
        username=user.username,
        role=user.role,
        permissions=sorted(resolve_user_permissions(user.role, user.custom_permissions)),
        is_active=user.is_active,
        created_at=user.created_at,
    )


@router.get("/permissions", response_model=PermissionMatrixResponse)
async def permission_matrix(_: User = Depends(get_current_user)) -> PermissionMatrixResponse:
    return PermissionMatrixResponse(roles={role: sorted(perms) for role, perms in ROLE_PERMISSIONS.items()})


@router.post("/bootstrap", response_model=TokenResponse)
async def bootstrap_admin(
    request: CreateUserRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    enforce_rate_limit(http_request, BOOTSTRAP_RATE, scope="auth_bootstrap")
    await db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 839201})
    total = await db.scalar(select(func.count()).select_from(User))
    if total and total > 0:
        raise HTTPException(status_code=400, detail="系统已初始化，请使用管理员账号创建用户。")

    password_hash, password_salt = hash_password(request.password)
    role = "admin"
    user = User(
        username=request.username,
        password_hash=password_hash,
        password_salt=password_salt,
        role=role,
        custom_permissions=sorted(get_permissions_for_role("admin")),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": role})
    return TokenResponse(access_token=token, user=to_user_profile(user))


@router.post("/register", response_model=TokenResponse)
async def register(
    request: RegisterRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    enforce_rate_limit(http_request, REGISTER_RATE, scope="auth_register")
    exists = await db.scalar(select(User).where(User.username == request.username))
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在。")

    password_hash, password_salt = hash_password(request.password)
    role = "user"
    user = User(
        username=request.username,
        password_hash=password_hash,
        password_salt=password_salt,
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": role})
    return TokenResponse(access_token=token, user=to_user_profile(user))


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    settings = get_settings()
    enforce_rate_limit(http_request, LOGIN_RATE, scope="auth_login")
    login_lockout.check_allowed(
        request.username,
        max_attempts=settings.login_lockout_max_attempts,
        window_seconds=settings.login_lockout_window_seconds,
    )
    stmt = select(User).where(User.username == request.username)
    user = await db.scalar(stmt)
    if user is None or not verify_password(request.password, user.password_hash, user.password_salt):
        login_lockout.record_failure(
            request.username,
            window_seconds=settings.login_lockout_window_seconds,
        )
        raise HTTPException(status_code=401, detail="用户名或密码错误。")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="用户已被禁用。")

    login_lockout.record_success(request.username)
    token = create_access_token({"sub": str(user.id), "role": user.role})
    return TokenResponse(access_token=token, user=to_user_profile(user))


@router.get("/me", response_model=UserProfile)
async def me(user: User = Depends(get_current_user)) -> UserProfile:
    return to_user_profile(user)


@router.get("/users", response_model=UserListResponse)
async def list_users(
    _: User = Depends(require_permissions("user:manage")),
    db: AsyncSession = Depends(get_db),
) -> UserListResponse:
    users = list((await db.scalars(select(User).order_by(User.created_at.asc()))).all())
    return UserListResponse(users=[to_user_profile(user) for user in users])


@router.post("/users", response_model=UserProfile)
async def create_user(
    request: CreateUserRequest,
    _: User = Depends(require_permissions("user:manage")),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    if request.role not in list_roles():
        raise HTTPException(status_code=400, detail=f"role 必须是: {', '.join(list_roles())}")
    exists = await db.scalar(select(User).where(User.username == request.username))
    if exists:
        raise HTTPException(status_code=400, detail="用户名已存在。")

    try:
        custom_permissions = validate_custom_permissions(request.custom_permissions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    password_hash, password_salt = hash_password(request.password)
    user = User(
        username=request.username,
        password_hash=password_hash,
        password_salt=password_salt,
        role=request.role,
        custom_permissions=custom_permissions,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return to_user_profile(user)


@router.patch("/users/{user_id}", response_model=UserProfile)
async def update_user(
    user_id: uuid.UUID,
    request: UpdateUserRequest,
    _: User = Depends(require_permissions("user:manage")),
    db: AsyncSession = Depends(get_db),
) -> UserProfile:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在。")

    if request.role is not None:
        if request.role not in list_roles():
            raise HTTPException(status_code=400, detail=f"role 必须是: {', '.join(list_roles())}")
        user.role = request.role
    if request.custom_permissions is not None:
        try:
            user.custom_permissions = validate_custom_permissions(request.custom_permissions)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if request.is_active is not None:
        user.is_active = request.is_active

    await db.commit()
    await db.refresh(user)
    return to_user_profile(user)
