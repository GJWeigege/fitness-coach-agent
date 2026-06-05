import uuid

import pytest
from httpx import AsyncClient

from app.db.models import AgentRun, AgentStep
from app.services.observability_service import ObservabilityService
from tests.test_auth import auth_headers, bootstrap_admin


@pytest.mark.asyncio
async def test_observability_runs_requires_permission(client: AsyncClient):
    response = await client.get("/observability/runs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_observability_list_and_detail(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    session_id = uuid.uuid4()
    svc = ObservabilityService()
    run = await svc.create_run(
        db_session,
        session_id=session_id,
        user_message_id=None,
        trace_id="trace-obs-1",
    )
    await svc.append_step(
        db_session,
        run.id,
        phase="planning",
        summary="plan",
        payload={"tasks": [{"agent": "training"}]},
    )
    await svc.finish_run(
        db_session,
        run.id,
        status="completed",
        intent="training",
        total_latency_ms=100,
    )
    await db_session.commit()

    listed = await client.get("/observability/runs", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] >= 1
    assert any(item["id"] == str(run.id) for item in body["runs"])

    detail = await client.get(f"/observability/runs/{run.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()
    assert data["trace_id"] == "trace-obs-1"
    assert data["intent"] == "training"
    assert len(data["timeline"]) >= 1
    assert data["timeline"][0]["phase"] == "planning"
    assert data["timeline"][0]["payload"]["tasks"][0]["agent"] == "training"


@pytest.mark.asyncio
async def test_observability_run_not_found(client: AsyncClient):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])
    missing = uuid.uuid4()
    response = await client.get(f"/observability/runs/{missing}", headers=headers)
    assert response.status_code == 404
