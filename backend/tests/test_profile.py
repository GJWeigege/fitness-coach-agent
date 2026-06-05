import pytest
from httpx import AsyncClient

from tests.test_auth import auth_headers


async def register_user(client: AsyncClient, username: str) -> dict:
    response = await client.post(
        "/auth/register",
        json={"username": username, "password": "Demo@123456"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_get_profile_returns_empty_when_missing(client: AsyncClient):
    user = await register_user(client, "profile_empty")
    headers = auth_headers(user["access_token"])

    response = await client.get("/profile", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == user["user"]["id"]
    assert body["age"] is None
    assert body["experience_level"] == "beginner"
    assert body["updated_at"] is None


@pytest.mark.asyncio
async def test_put_profile_creates_and_gets(client: AsyncClient):
    user = await register_user(client, "profile_upsert")
    headers = auth_headers(user["access_token"])
    payload = {
        "age": 28,
        "sex": "male",
        "height_cm": 175.5,
        "weight_kg": 72.0,
        "goals": ["增肌", "提升耐力"],
        "experience_level": "intermediate",
        "injuries": ["左膝旧伤"],
        "equipment": ["哑铃", "跑步机"],
        "diet_preference": "高蛋白",
    }

    put = await client.put("/profile", headers=headers, json=payload)
    assert put.status_code == 200, put.text
    saved = put.json()
    assert saved["age"] == 28
    assert saved["goals"] == ["增肌", "提升耐力"]
    assert saved["experience_level"] == "intermediate"
    assert saved["updated_at"] is not None

    get_resp = await client.get("/profile", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["weight_kg"] == 72.0


@pytest.mark.asyncio
async def test_put_profile_rejects_invalid_experience_level(client: AsyncClient):
    user = await register_user(client, "profile_invalid_level")
    headers = auth_headers(user["access_token"])

    response = await client.put(
        "/profile",
        headers=headers,
        json={"experience_level": "expert"},
    )
    assert response.status_code == 400
    assert "experience_level" in response.json()["detail"]


@pytest.mark.asyncio
async def test_training_logs_list_and_create(client: AsyncClient):
    user = await register_user(client, "profile_logs")
    headers = auth_headers(user["access_token"])

    empty = await client.get("/profile/training-logs", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["logs"] == []

    created = await client.post(
        "/profile/training-logs",
        headers=headers,
        json={
            "session_date": "2026-06-01",
            "activity_type": "strength",
            "duration_min": 45,
            "intensity": "moderate",
            "notes": "深蹲 5x5",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["activity_type"] == "strength"
    assert body["duration_min"] == 45
    assert body["notes"] == "深蹲 5x5"

    listed = await client.get("/profile/training-logs", headers=headers)
    assert listed.status_code == 200
    logs = listed.json()["logs"]
    assert len(logs) == 1
    assert logs[0]["id"] == body["id"]


@pytest.mark.asyncio
async def test_profile_requires_auth(client: AsyncClient):
    response = await client.get("/profile")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_training_log_create_validates_duration(client: AsyncClient):
    user = await register_user(client, "profile_log_invalid")
    headers = auth_headers(user["access_token"])

    response = await client.post(
        "/profile/training-logs",
        headers=headers,
        json={
            "session_date": "2026-06-02",
            "activity_type": "run",
            "duration_min": 0,
            "intensity": "easy",
        },
    )
    assert response.status_code == 422
