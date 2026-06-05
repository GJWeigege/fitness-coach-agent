import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import RateLimitRule, reset_rate_limiter_for_tests
from app.db.models import ChatMessage
from tests.test_auth import auth_headers, bootstrap_admin
from tests.test_chat_sessions import create_admin


async def register_user(client: AsyncClient, username: str) -> dict:
    response = await client.post(
        "/auth/register",
        json={"username": username, "password": "Demo@123456"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def create_session_with_assistant_message(
    client: AsyncClient,
    db_session: AsyncSession,
    username: str,
) -> tuple[dict, uuid.UUID, uuid.UUID]:
    user = await register_user(client, username)
    headers = auth_headers(user["access_token"])
    created = await client.post("/chat/sessions", headers=headers, json={"title": "反馈测试"})
    session_id = uuid.UUID(created.json()["id"])
    assistant = ChatMessage(session_id=session_id, role="assistant", content="建议每周训练 3-4 次。")
    user_msg = ChatMessage(session_id=session_id, role="user", content="怎么安排训练？")
    db_session.add_all([user_msg, assistant])
    await db_session.commit()
    await db_session.refresh(assistant)
    return user, assistant.id, session_id


@pytest.mark.asyncio
async def test_feedback_up_on_assistant_message(client: AsyncClient, db_session: AsyncSession):
    user, message_id, _ = await create_session_with_assistant_message(client, db_session, "feedback_up")
    headers = auth_headers(user["access_token"])

    response = await client.post(
        f"/chat/messages/{message_id}/feedback",
        headers=headers,
        json={"rating": "up"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["rating"] == "up"
    assert body["message_id"] == str(message_id)


@pytest.mark.asyncio
async def test_feedback_down_on_assistant_message(client: AsyncClient, db_session: AsyncSession):
    user, message_id, _ = await create_session_with_assistant_message(client, db_session, "feedback_down")
    headers = auth_headers(user["access_token"])

    response = await client.post(
        f"/chat/messages/{message_id}/feedback",
        headers=headers,
        json={"rating": "down"},
    )
    assert response.status_code == 200
    assert response.json()["rating"] == "down"


@pytest.mark.asyncio
async def test_feedback_rejects_user_message(client: AsyncClient, db_session: AsyncSession):
    user, _, session_id = await create_session_with_assistant_message(client, db_session, "feedback_user")
    headers = auth_headers(user["access_token"])
    user_record = (
        await db_session.execute(
            ChatMessage.__table__.select().where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "user",
            )
        )
    ).first()
    user_message_id = user_record[0]

    response = await client.post(
        f"/chat/messages/{user_message_id}/feedback",
        headers=headers,
        json={"rating": "up"},
    )
    assert response.status_code == 400
    assert "教练回复" in response.json()["detail"]


@pytest.mark.asyncio
async def test_feedback_forbidden_for_other_user(client: AsyncClient, db_session: AsyncSession):
    owner, message_id, _ = await create_session_with_assistant_message(client, db_session, "feedback_owner")
    other = await register_user(client, "feedback_other")
    headers = auth_headers(other["access_token"])

    response = await client.post(
        f"/chat/messages/{message_id}/feedback",
        headers=headers,
        json={"rating": "up"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_feedback_any_session(client: AsyncClient, db_session: AsyncSession):
    admin = await create_admin(client)
    _, message_id, _ = await create_session_with_assistant_message(client, db_session, "feedback_admin_target")
    headers = auth_headers(admin["access_token"])

    response = await client.post(
        f"/chat/messages/{message_id}/feedback",
        headers=headers,
        json={"rating": "up"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_feedback_rate_limit(client: AsyncClient, db_session: AsyncSession):
    user, message_id, _ = await create_session_with_assistant_message(client, db_session, "feedback_rate")
    headers = auth_headers(user["access_token"])
    tight_limit = RateLimitRule(max_requests=2, window_seconds=60)
    reset_rate_limiter_for_tests()  # setup POST already counted; clear before measuring feedback limit

    with (
        patch("app.api.chat.CHAT_WRITE_RATE", tight_limit),
        patch("app.api.chat.enforce_rate_limit", lambda *_a, **_k: None),
    ):
        first = await client.post(
            f"/chat/messages/{message_id}/feedback",
            headers=headers,
            json={"rating": "up"},
        )
        second = await client.post(
            f"/chat/messages/{message_id}/feedback",
            headers=headers,
            json={"rating": "down"},
        )
        third = await client.post(
            f"/chat/messages/{message_id}/feedback",
            headers=headers,
            json={"rating": "up"},
        )
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
