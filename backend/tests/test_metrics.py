import uuid

import pytest
from httpx import AsyncClient

from app.services.observability_service import ObservabilityService
from tests.test_auth import auth_headers, bootstrap_admin


@pytest.mark.asyncio
async def test_agent_summary_requires_permission(client: AsyncClient):
    response = await client.get("/observability/metrics/agent-summary")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_agent_summary_empty(client: AsyncClient):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])
    response = await client.get("/observability/metrics/agent-summary", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_runs"] == 0
    assert body["success_rate"] == 0
    assert body["p95_latency_ms"] == 0


@pytest.mark.asyncio
async def test_agent_summary_aggregates_runs(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])
    svc = ObservabilityService()
    session_id = uuid.uuid4()

    for status, latency in [("completed", 100), ("completed", 200), ("degraded", 300)]:
        run = await svc.create_run(
            db_session,
            session_id=session_id,
            user_message_id=None,
            trace_id=f"trace-{status}-{latency}",
        )
        await svc.finish_run(
            db_session,
            run.id,
            status=status,
            intent="training",
            total_latency_ms=latency,
        )
    await db_session.commit()

    response = await client.get("/observability/metrics/agent-summary?days=7", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_runs"] == 3
    assert body["success_rate"] == round(2 / 3, 4)
    assert body["degraded_rate"] == round(1 / 3, 4)
    assert body["avg_step_count"] >= 0
    assert body["p95_latency_ms"] >= 200
