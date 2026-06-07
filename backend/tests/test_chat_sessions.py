import uuid
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import RateLimitRule
from app.db.models import AgentRun, AgentStep, ChatMessage, ChatSession
from tests.test_auth import auth_headers, bootstrap_admin


async def register_user(client: AsyncClient, username: str) -> dict:
    response = await client.post(
        "/auth/register",
        json={"username": username, "password": "Demo@123456"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_list_sessions_requires_auth(client: AsyncClient):
    response = await client.get("/chat/sessions")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_and_list_sessions_scoped_to_user(client: AsyncClient):
    user_a = await register_user(client, "chat_user_a")
    user_b = await register_user(client, "chat_user_b")
    headers_a = auth_headers(user_a["access_token"])
    headers_b = auth_headers(user_b["access_token"])

    create_a = await client.post("/chat/sessions", headers=headers_a, json={"title": "训练计划"})
    assert create_a.status_code == 200, create_a.text
    session_a = create_a.json()
    assert session_a["title"] == "训练计划"
    assert session_a["user_id"] == user_a["user"]["id"]

    create_b = await client.post("/chat/sessions", headers=headers_b, json={"title": "营养咨询"})
    assert create_b.status_code == 200

    list_a = await client.get("/chat/sessions", headers=headers_a)
    assert list_a.status_code == 200
    sessions_a = list_a.json()["sessions"]
    assert len(sessions_a) == 1
    assert sessions_a[0]["id"] == session_a["id"]

    list_b = await client.get("/chat/sessions", headers=headers_b)
    assert len(list_b.json()["sessions"]) == 1
    assert list_b.json()["sessions"][0]["title"] == "营养咨询"


async def create_admin(client: AsyncClient) -> dict:
    admin = await bootstrap_admin(client)
    return admin


@pytest.mark.asyncio
async def test_admin_can_list_all_sessions(client: AsyncClient):
    admin = await create_admin(client)
    user = await register_user(client, "chat_regular")
    user_headers = auth_headers(user["access_token"])
    admin_headers = auth_headers(admin["access_token"])

    created = await client.post("/chat/sessions", headers=user_headers, json={"title": "用户会话"})
    assert created.status_code == 200
    session_id = created.json()["id"]

    listed = await client.get("/chat/sessions", headers=admin_headers)
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["sessions"]}
    assert session_id in ids


@pytest.mark.asyncio
async def test_create_session_rejects_benchmark_prefix(client: AsyncClient):
    user = await register_user(client, "bench_title_user")
    headers = auth_headers(user["access_token"])

    response = await client.post(
        "/chat/sessions",
        headers=headers,
        json={"title": "benchmark:my-test"},
    )
    assert response.status_code == 400
    assert "评测专用前缀" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rename_session_rejects_benchmark_prefix(client: AsyncClient):
    user = await register_user(client, "bench_rename_user")
    headers = auth_headers(user["access_token"])
    created = await client.post("/chat/sessions", headers=headers, json={"title": "正常标题"})
    session_id = created.json()["id"]

    response = await client.patch(
        f"/chat/sessions/{session_id}",
        headers=headers,
        json={"title": "benchmark:evil"},
    )
    assert response.status_code == 400
    assert "评测专用前缀" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rename_session(client: AsyncClient):
    user = await register_user(client, "rename_user")
    headers = auth_headers(user["access_token"])
    created = await client.post("/chat/sessions", headers=headers, json={"title": "旧标题"})
    session_id = created.json()["id"]

    renamed = await client.patch(
        f"/chat/sessions/{session_id}",
        headers=headers,
        json={"title": "新标题"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "新标题"


@pytest.mark.asyncio
async def test_delete_session_removes_messages(client: AsyncClient, db_session: AsyncSession):
    user = await register_user(client, "delete_user")
    headers = auth_headers(user["access_token"])
    created = await client.post("/chat/sessions", headers=headers)
    session_id = uuid.UUID(created.json()["id"])

    db_session.add(ChatMessage(session_id=session_id, role="user", content="你好"))
    db_session.add(ChatMessage(session_id=session_id, role="assistant", content="你好，有什么可以帮你？"))
    await db_session.commit()

    deleted = await client.delete(f"/chat/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    remaining_sessions = list((await db_session.scalars(select(ChatSession))).all())
    remaining_messages = list((await db_session.scalars(select(ChatMessage))).all())
    assert remaining_sessions == []
    assert remaining_messages == []


@pytest.mark.asyncio
async def test_cannot_access_other_user_session_messages(client: AsyncClient, db_session: AsyncSession):
    owner = await register_user(client, "owner_user")
    other = await register_user(client, "other_user")
    owner_headers = auth_headers(owner["access_token"])
    other_headers = auth_headers(other["access_token"])

    created = await client.post("/chat/sessions", headers=owner_headers)
    session_id = uuid.UUID(created.json()["id"])
    db_session.add(ChatMessage(session_id=session_id, role="user", content="私密问题"))
    await db_session.commit()

    response = await client.get(f"/chat/sessions/{session_id}/messages", headers=other_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_session_messages(client: AsyncClient, db_session: AsyncSession):
    user = await register_user(client, "messages_user")
    headers = auth_headers(user["access_token"])
    created = await client.post("/chat/sessions", headers=headers)
    session_id = uuid.UUID(created.json()["id"])

    db_session.add(ChatMessage(session_id=session_id, role="user", content="如何增肌？"))
    db_session.add(
        ChatMessage(
            session_id=session_id,
            role="assistant",
            content="建议渐进超负荷训练。",
            retrieved_chunks={"items": [{"content": "增肌知识", "score": 0.9}]},
        )
    )
    await db_session.commit()

    response = await client.get(f"/chat/sessions/{session_id}/messages", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == str(session_id)
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][1]["role"] == "assistant"
    assert body["messages"][1]["citations"][0]["content"] == "增肌知识"


@pytest.mark.asyncio
async def test_list_session_messages_includes_persisted_agent_steps(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user = await register_user(client, "steps_user")
    headers = auth_headers(user["access_token"])
    created = await client.post("/chat/sessions", headers=headers)
    session_id = uuid.UUID(created.json()["id"])
    run_id = uuid.uuid4()

    db_session.add(ChatMessage(session_id=session_id, role="user", content="如何增肌？"))
    db_session.add(
        ChatMessage(
            session_id=session_id,
            role="assistant",
            content="建议渐进超负荷训练。",
            agent_run_id=run_id,
            agent_steps={
                "items": [
                    {"phase": "routing", "summary": "正在识别用户意图…"},
                    {"phase": "planning", "summary": "正在制定执行计划…"},
                ]
            },
        )
    )
    await db_session.commit()

    response = await client.get(f"/chat/sessions/{session_id}/messages", headers=headers)
    assert response.status_code == 200
    assistant = response.json()["messages"][1]
    assert len(assistant["steps"]) == 2
    assert assistant["steps"][0]["phase"] == "routing"
    assert assistant["steps"][1]["phase"] == "planning"


@pytest.mark.asyncio
async def test_list_session_messages_falls_back_to_agent_run_steps(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user = await register_user(client, "fallback_steps_user")
    headers = auth_headers(user["access_token"])
    created = await client.post("/chat/sessions", headers=headers)
    session_id = uuid.UUID(created.json()["id"])
    run_id = uuid.uuid4()

    db_session.add(
        AgentRun(
            id=run_id,
            trace_id="trace-fallback",
            session_id=session_id,
            status="completed",
        )
    )
    db_session.add(ChatMessage(session_id=session_id, role="user", content="如何增肌？"))
    db_session.add(
        ChatMessage(
            session_id=session_id,
            role="assistant",
            content="建议渐进超负荷训练。",
            agent_run_id=run_id,
        )
    )
    db_session.add(
        AgentStep(
            run_id=run_id,
            step_index=0,
            phase="planning",
            summary="execution plan",
            payload={"plan": {"tasks": []}},
        )
    )
    await db_session.commit()

    response = await client.get(f"/chat/sessions/{session_id}/messages", headers=headers)
    assert response.status_code == 200
    assistant = response.json()["messages"][1]
    assert len(assistant["steps"]) == 1
    assert assistant["steps"][0]["phase"] == "planning"
    assert assistant["steps"][0]["summary"] == "已制定执行计划"


@pytest.mark.asyncio
async def test_list_session_messages_falls_back_when_agent_steps_malformed(
    client: AsyncClient,
    db_session: AsyncSession,
):
    user = await register_user(client, "malformed_steps_user")
    headers = auth_headers(user["access_token"])
    created = await client.post("/chat/sessions", headers=headers)
    session_id = uuid.UUID(created.json()["id"])
    run_id = uuid.uuid4()

    db_session.add(
        AgentRun(
            id=run_id,
            trace_id="trace-malformed",
            session_id=session_id,
            status="completed",
            step_count=1,
            intent="training",
        )
    )
    db_session.add(ChatMessage(session_id=session_id, role="user", content="如何增肌？"))
    db_session.add(
        ChatMessage(
            session_id=session_id,
            role="assistant",
            content="建议渐进超负荷训练。",
            agent_run_id=run_id,
            agent_steps={"items": [{"phase": "broken"}]},
            latency_ms=1200,
        )
    )
    db_session.add(
        AgentStep(
            run_id=run_id,
            step_index=0,
            phase="planning",
            summary="execution plan",
            payload={"plan": {"tasks": []}, "cot": "hidden"},
        )
    )
    await db_session.commit()

    response = await client.get(f"/chat/sessions/{session_id}/messages", headers=headers)
    assert response.status_code == 200
    assistant = response.json()["messages"][1]
    assert len(assistant["steps"]) == 1
    assert assistant["steps"][0]["phase"] == "planning"
    assert "cot" not in (assistant["steps"][0].get("detail") or {})
    assert assistant["run_status"] == "completed"
    assert assistant["step_count"] == 1
    assert assistant["intent"] == "training"
    assert assistant["latency_ms"] == 1200


@pytest.mark.asyncio
async def test_create_session_rate_limit(client: AsyncClient):
    user = await register_user(client, "rate_user")
    headers = auth_headers(user["access_token"])
    tight_limit = RateLimitRule(max_requests=2, window_seconds=60)

    with (
        patch("app.api.chat.CHAT_WRITE_RATE", tight_limit),
        patch("app.api.chat.enforce_rate_limit", lambda *_a, **_k: None),
    ):
        first = await client.post("/chat/sessions", headers=headers, json={"title": "1"})
        second = await client.post("/chat/sessions", headers=headers, json={"title": "2"})
        third = await client.post("/chat/sessions", headers=headers, json={"title": "3"})
    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
