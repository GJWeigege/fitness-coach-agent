import pytest
from httpx import AsyncClient

from app.auth.permissions import (
    ROLE_PERMISSIONS,
    get_permissions_for_role,
    list_roles,
    resolve_user_permissions,
    validate_custom_permissions,
)


async def bootstrap_admin(client: AsyncClient, username: str = "admin", password: str = "Admin@123456") -> dict:
    response = await client.post(
        "/auth/bootstrap",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_role_permissions_matrix_matches_design():
    assert set(list_roles()) == {"admin", "kb_editor", "user"}
    assert "user:manage" in get_permissions_for_role("admin")
    assert "user:manage" not in get_permissions_for_role("user")
    assert "knowledge:write" in get_permissions_for_role("kb_editor")
    assert "benchmark:run" in get_permissions_for_role("admin")


def test_resolve_user_permissions_merges_custom():
    perms = resolve_user_permissions("user", ["knowledge:read"])
    assert "chat:send" in perms
    assert "knowledge:read" in perms
    assert "user:manage" not in perms


def test_validate_custom_permissions_rejects_unknown():
    with pytest.raises(ValueError, match="未知权限"):
        validate_custom_permissions(["not:a:permission"])


@pytest.mark.asyncio
async def test_bootstrap_creates_admin(client: AsyncClient):
    data = await bootstrap_admin(client)
    assert data["token_type"] == "bearer"
    assert data["user"]["role"] == "admin"
    assert "user:manage" in data["user"]["permissions"]


@pytest.mark.asyncio
async def test_bootstrap_rejects_when_users_exist(client: AsyncClient):
    await bootstrap_admin(client)
    response = await client.post(
        "/auth/bootstrap",
        json={"username": "admin2", "password": "Admin@123456"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_register_defaults_to_user_role(client: AsyncClient):
    response = await client.post(
        "/auth/register",
        json={"username": "coach_user", "password": "Demo@123456"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "user"
    assert "chat:send" in body["user"]["permissions"]
    assert "user:manage" not in body["user"]["permissions"]


@pytest.mark.asyncio
async def test_register_rejects_duplicate_username(client: AsyncClient):
    payload = {"username": "dup_user", "password": "Demo@123456"}
    first = await client.post("/auth/register", json=payload)
    second = await client.post("/auth/register", json=payload)
    assert first.status_code == 200
    assert second.status_code == 400


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    await client.post("/auth/register", json={"username": "login_user", "password": "Demo@123456"})
    response = await client.post(
        "/auth/login",
        json={"username": "login_user", "password": "Demo@123456"},
    )
    assert response.status_code == 200
    assert response.json()["user"]["username"] == "login_user"


@pytest.mark.asyncio
async def test_login_rejects_bad_password(client: AsyncClient):
    await client.post("/auth/register", json={"username": "bad_pw_user", "password": "Demo@123456"})
    response = await client.post(
        "/auth/login",
        json={"username": "bad_pw_user", "password": "Wrong@123456"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_current_user(client: AsyncClient):
    registered = await client.post(
        "/auth/register",
        json={"username": "me_user", "password": "Demo@123456"},
    )
    token = registered.json()["access_token"]
    response = await client.get("/auth/me", headers=auth_headers(token))
    assert response.status_code == 200
    assert response.json()["username"] == "me_user"
    assert response.json()["role"] == "user"


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient):
    response = await client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_permissions_matrix_endpoint(client: AsyncClient):
    admin = await bootstrap_admin(client)
    response = await client.get("/auth/permissions", headers=auth_headers(admin["access_token"]))
    assert response.status_code == 200
    roles = response.json()["roles"]
    assert set(roles.keys()) == set(ROLE_PERMISSIONS.keys())
    assert "benchmark:read" in roles["admin"]


@pytest.mark.asyncio
async def test_user_cannot_list_users(client: AsyncClient):
    await bootstrap_admin(client)
    registered = await client.post(
        "/auth/register",
        json={"username": "regular", "password": "Demo@123456"},
    )
    token = registered.json()["access_token"]
    response = await client.get("/auth/users", headers=auth_headers(token))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_create_and_update_users(client: AsyncClient):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    create = await client.post(
        "/auth/users",
        headers=headers,
        json={
            "username": "kb_demo",
            "password": "Demo@123456",
            "role": "kb_editor",
        },
    )
    assert create.status_code == 200
    created = create.json()
    assert created["role"] == "kb_editor"
    assert "knowledge:write" in created["permissions"]

    update = await client.patch(
        f"/auth/users/{created['id']}",
        headers=headers,
        json={"is_active": False},
    )
    assert update.status_code == 200
    assert update.json()["is_active"] is False


@pytest.mark.asyncio
async def test_admin_create_user_rejects_invalid_role(client: AsyncClient):
    admin = await bootstrap_admin(client)
    response = await client.post(
        "/auth/users",
        headers=auth_headers(admin["access_token"]),
        json={
            "username": "bad_role",
            "password": "Demo@123456",
            "role": "agent",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_admin_list_users(client: AsyncClient):
    admin = await bootstrap_admin(client, username="list_admin")
    await client.post(
        "/auth/register",
        json={"username": "listed_user", "password": "Demo@123456"},
    )
    response = await client.get("/auth/users", headers=auth_headers(admin["access_token"]))
    assert response.status_code == 200
    usernames = {user["username"] for user in response.json()["users"]}
    assert {"list_admin", "listed_user"} <= usernames
