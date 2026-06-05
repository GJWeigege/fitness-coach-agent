import json
import uuid

import pytest
from httpx import AsyncClient

from app.db.models import User
from app.services.benchmark_runner import BenchmarkRunner, BenchmarkSample
from app.services.benchmark_service import BenchmarkService
from app.services.chat_service import ChatService
from app.services.rag_service import RagService
from tests.coach_mocks import MockDashScopeClient
from tests.test_auth import auth_headers, bootstrap_admin
from tests.test_benchmark import benchmark_settings  # noqa: F401 — fixture


@pytest.mark.asyncio
async def test_benchmark_runs_requires_auth(client: AsyncClient):
    response = await client.post("/benchmark/runs", json={"dataset_name": "coach_eval"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_benchmark_create_run_returns_202(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    response = await client.post(
        "/benchmark/runs",
        json={"dataset_name": "coach_eval"},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "pending"
    assert body["dataset_name"] == "coach_eval"
    run_id = body["id"]

    detail = await client.get(f"/benchmark/runs/{run_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_benchmark_execute_run_status_machine(
    client: AsyncClient, db_session, benchmark_settings, monkeypatch
):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    user = User(username="coach_demo", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.commit()

    planner_plan = json.dumps(
        {
            "tasks": [{"agent": "training", "goal": "增肌"}],
            "constraints": [],
            "estimated_tools": ["knowledge_search"],
        },
        ensure_ascii=False,
    )
    llm = MockDashScopeClient(
        chat_responses=[planner_plan],
        tool_stream_chunks=["训练建议正文。"],
        stream_chunks=["训练建议正文。"],
    )
    chat = ChatService(llm_client=llm, rag_service=RagService(llm_client=llm))
    service = BenchmarkService(chat_service=chat)
    service._runner = BenchmarkRunner(chat)

    tiny_sample = BenchmarkSample(
        id="eval-tiny",
        question="我想力量训练增肌",
        expected_intent="training",
    )
    monkeypatch.setattr(
        "app.services.benchmark_service.load_benchmark_dataset",
        lambda _path: [tiny_sample],
    )

    run = await service.create_run(db_session, dataset_name="coach_eval")
    await db_session.commit()

    await service.execute_run(db_session, run.id)
    await db_session.commit()

    detail = await client.get(f"/benchmark/runs/{run.id}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()
    assert data["status"] == "completed"
    assert data["metrics"] is not None
    assert "intent_accuracy" in data["metrics"]
    assert len(data["results"]) == 1


@pytest.mark.asyncio
async def test_benchmark_list_runs(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    service = BenchmarkService()
    run = await service.create_run(db_session, dataset_name="coach_eval")
    await db_session.commit()

    listed = await client.get("/benchmark/runs", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] >= 1
    assert any(item["id"] == str(run.id) for item in body["runs"])


@pytest.mark.asyncio
async def test_benchmark_run_not_found(client: AsyncClient):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])
    missing = uuid.uuid4()
    response = await client.get(f"/benchmark/runs/{missing}", headers=headers)
    assert response.status_code == 404
