import json
import uuid

import pytest
from httpx import AsyncClient

from app.db.models import ChatSession, User
from app.services.benchmark_runner import BenchmarkRunner, BenchmarkSample
from app.services.benchmark_service import BenchmarkService
from app.services.chat_service import ChatService
from app.services.rag_service import RagService
from tests.coach_mocks import MockDashScopeClient
from tests.test_auth import auth_headers, bootstrap_admin
from tests.test_benchmark import benchmark_settings  # noqa: F401 — fixture


def _admin_id(admin: dict) -> uuid.UUID:
    return uuid.UUID(admin["user"]["id"])


@pytest.mark.asyncio
async def test_benchmark_runs_requires_auth(client: AsyncClient):
    response = await client.post("/benchmark/runs", json={"dataset_name": "coach_eval"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_benchmark_create_run_returns_202(client: AsyncClient, db_session, monkeypatch):
    async def noop_background(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("app.api.benchmark._execute_benchmark_background", noop_background)

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

    run = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin),
    )
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
async def test_benchmark_execute_run_sample_limit(
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

    samples = [
        BenchmarkSample(id=f"eval-{idx}", question=f"问题{idx}", expected_intent="training")
        for idx in range(3)
    ]
    monkeypatch.setattr(
        "app.services.benchmark_service.load_benchmark_dataset",
        lambda _path: samples,
    )

    run = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin),
    )
    await db_session.commit()

    await service.execute_run(db_session, run.id, sample_limit=2)
    await db_session.commit()

    detail = await client.get(f"/benchmark/runs/{run.id}", headers=headers)
    data = detail.json()
    assert data["status"] == "completed"
    assert len(data["results"]) == 2
    assert data["metrics"]["subset_limit"] == 2
    assert data["metrics"]["planned_sample_count"] == 2
    assert data["metrics"]["dataset_total"] == 3


@pytest.mark.asyncio
async def test_benchmark_cancel_pending_run(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    service = BenchmarkService()
    run = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin),
    )
    await db_session.commit()

    response = await client.post(f"/benchmark/runs/{run.id}/cancel", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cancelled"

    detail = await client.get(f"/benchmark/runs/{run.id}", headers=headers)
    assert detail.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_benchmark_cancel_running_run(
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

    samples = [
        BenchmarkSample(id=f"eval-{idx}", question=f"问题{idx}", expected_intent="training")
        for idx in range(3)
    ]
    monkeypatch.setattr(
        "app.services.benchmark_service.load_benchmark_dataset",
        lambda _path: samples,
    )

    run = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin),
    )
    await db_session.commit()

    original_run_sample = service._runner.run_sample
    call_count = 0

    async def run_sample_and_cancel_after_first(*args, **kwargs):
        nonlocal call_count
        result = await original_run_sample(*args, **kwargs)
        call_count += 1
        if call_count == 1:
            await service.cancel_run(db_session, run.id)
            await db_session.commit()
        return result

    monkeypatch.setattr(service._runner, "run_sample", run_sample_and_cancel_after_first)

    await service.execute_run(db_session, run.id)
    await db_session.commit()

    detail = await client.get(f"/benchmark/runs/{run.id}", headers=headers)
    data = detail.json()
    assert data["status"] == "cancelled"
    assert len(data["results"]) == 1
    assert data["metrics"]["sample_count"] == 1


@pytest.mark.asyncio
async def test_benchmark_cancel_completed_run_conflict(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    service = BenchmarkService()
    run = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin),
    )
    run.status = "completed"
    await db_session.commit()

    response = await client.post(f"/benchmark/runs/{run.id}/cancel", headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "该评测已结束，无法取消。"


@pytest.mark.asyncio
async def test_benchmark_cancel_requires_auth(client: AsyncClient, db_session):
    owner = User(username="cancel_owner", password_hash="h", password_salt="s")
    db_session.add(owner)
    await db_session.flush()

    service = BenchmarkService()
    run = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=owner.id,
    )
    await db_session.commit()

    response = await client.post(f"/benchmark/runs/{run.id}/cancel")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_benchmark_cancel_forbidden_for_regular_user(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    admin_headers = auth_headers(admin["access_token"])

    service = BenchmarkService()
    run = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin),
    )
    await db_session.commit()

    registered = await client.post(
        "/auth/register",
        json={"username": "bench_user", "password": "User@123456"},
    )
    assert registered.status_code == 200, registered.text
    user_headers = auth_headers(registered.json()["access_token"])

    response = await client.post(f"/benchmark/runs/{run.id}/cancel", headers=user_headers)
    assert response.status_code == 403

    detail = await client.get(f"/benchmark/runs/{run.id}", headers=admin_headers)
    assert detail.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_benchmark_create_run_rejects_both_subset_options(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    response = await client.post(
        "/benchmark/runs",
        json={"sample_limit": 10, "sample_ids": ["eval-001"]},
        headers=headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_benchmark_create_run_conflict_when_active(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    service = BenchmarkService()
    await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin),
    )
    await db_session.commit()

    response = await client.post(
        "/benchmark/runs",
        json={"dataset_name": "coach_eval"},
        headers=headers,
    )
    assert response.status_code == 409
    assert "已有评测正在运行" in response.json()["detail"]


@pytest.mark.asyncio
async def test_benchmark_create_run_sample_limit_http(
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

    samples = [
        BenchmarkSample(id=f"eval-{idx}", question=f"问题{idx}", expected_intent="training")
        for idx in range(3)
    ]
    monkeypatch.setattr(
        "app.services.benchmark_service.load_benchmark_dataset",
        lambda _path: samples,
    )

    async def immediate_background(
        run_id: uuid.UUID,
        *,
        sample_limit: int | None = None,
        sample_ids: list[str] | None = None,
    ) -> None:
        service = BenchmarkService(chat_service=chat)
        service._runner = BenchmarkRunner(chat)
        await service.execute_run(
            db_session,
            run_id,
            sample_limit=sample_limit,
            sample_ids=sample_ids,
        )

    monkeypatch.setattr("app.api.benchmark._execute_benchmark_background", immediate_background)

    response = await client.post(
        "/benchmark/runs",
        json={"sample_limit": 2},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    run_id = uuid.UUID(response.json()["id"])

    await immediate_background(run_id, sample_limit=2)
    await db_session.commit()

    detail = await client.get(f"/benchmark/runs/{run_id}", headers=headers)
    data = detail.json()
    assert data["status"] == "completed"
    assert len(data["results"]) == 2
    assert data["metrics"]["subset_limit"] == 2


@pytest.mark.asyncio
async def test_benchmark_read_forbidden_for_regular_user(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    admin_headers = auth_headers(admin["access_token"])

    service = BenchmarkService()
    run = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin),
    )
    await db_session.commit()

    registered = await client.post(
        "/auth/register",
        json={"username": "bench_read_user", "password": "User@123456"},
    )
    assert registered.status_code == 200, registered.text
    user_headers = auth_headers(registered.json()["access_token"])

    list_resp = await client.get("/benchmark/runs", headers=user_headers)
    assert list_resp.status_code == 403

    detail_resp = await client.get(f"/benchmark/runs/{run.id}", headers=user_headers)
    assert detail_resp.status_code == 403

    create_resp = await client.post(
        "/benchmark/runs",
        json={"dataset_name": "coach_eval"},
        headers=user_headers,
    )
    assert create_resp.status_code == 403


@pytest.mark.asyncio
async def test_benchmark_reconcile_stale_runs(db_session):
    from app.db.models import BenchmarkRun

    admin = User(username="bench_admin", password_hash="h", password_salt="s", role="admin")
    db_session.add(admin)
    await db_session.flush()

    pending = BenchmarkRun(
        dataset_name="coach_eval",
        created_by_user_id=admin.id,
        status="pending",
    )
    running = BenchmarkRun(
        dataset_name="coach_eval",
        created_by_user_id=admin.id,
        status="running",
    )
    completed = BenchmarkRun(
        dataset_name="coach_eval",
        created_by_user_id=admin.id,
        status="completed",
    )
    db_session.add_all([pending, running, completed])
    await db_session.commit()

    service = BenchmarkService()
    reconciled = await service.reconcile_stale_runs(db_session)
    await db_session.commit()

    assert reconciled == 2
    await db_session.refresh(pending)
    await db_session.refresh(running)
    await db_session.refresh(completed)
    assert pending.status == "failed"
    assert running.status == "failed"
    assert completed.status == "completed"


@pytest.mark.asyncio
async def test_benchmark_runs_visible_to_all_admins(client: AsyncClient, db_session):
    from app.auth.password import hash_password

    admin_a = await bootstrap_admin(client, username="bench_admin_a")
    password_hash, password_salt = hash_password("Admin@123456")
    admin_b = User(
        username="bench_admin_b",
        password_hash=password_hash,
        password_salt=password_salt,
        role="admin",
        is_active=True,
    )
    db_session.add(admin_b)
    await db_session.commit()

    login_b = await client.post(
        "/auth/login",
        json={"username": "bench_admin_b", "password": "Admin@123456"},
    )
    assert login_b.status_code == 200, login_b.text

    headers_a = auth_headers(admin_a["access_token"])
    headers_b = auth_headers(login_b.json()["access_token"])

    service = BenchmarkService()
    run_a = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin_a),
    )
    await db_session.commit()

    listed_b = await client.get("/benchmark/runs", headers=headers_b)
    assert listed_b.status_code == 200
    assert any(item["id"] == str(run_a.id) for item in listed_b.json()["runs"])

    detail_b = await client.get(f"/benchmark/runs/{run_a.id}", headers=headers_b)
    assert detail_b.status_code == 200
    assert detail_b.json()["status"] == "pending"


@pytest.mark.asyncio
async def test_benchmark_chat_sessions_hidden_from_list(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client, username="bench_chat_admin")
    headers = auth_headers(admin["access_token"])

    coach = User(username="coach_demo", password_hash="h", password_salt="s")
    db_session.add(coach)
    await db_session.flush()

    normal = ChatSession(user_id=coach.id, title="我的训练计划")
    benchmark = ChatSession(user_id=coach.id, title="benchmark:eval-001")
    db_session.add_all([normal, benchmark])
    await db_session.commit()

    listed = await client.get("/chat/sessions", headers=headers)
    assert listed.status_code == 200
    titles = {item["title"] for item in listed.json()["sessions"]}
    assert "我的训练计划" in titles
    assert "benchmark:eval-001" not in titles


@pytest.mark.asyncio
async def test_benchmark_chat_session_messages_forbidden(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    coach = User(username="coach_demo", password_hash="h", password_salt="s")
    db_session.add(coach)
    await db_session.flush()

    benchmark_session = ChatSession(user_id=coach.id, title="benchmark:eval-001")
    db_session.add(benchmark_session)
    await db_session.commit()

    admin_resp = await client.get(
        f"/chat/sessions/{benchmark_session.id}/messages",
        headers=headers,
    )
    assert admin_resp.status_code == 403


@pytest.mark.asyncio
async def test_benchmark_list_runs(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    service = BenchmarkService()
    run = await service.create_run(
        db_session,
        dataset_name="coach_eval",
        created_by_user_id=_admin_id(admin),
    )
    await db_session.commit()

    listed = await client.get("/benchmark/runs", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] >= 1
    assert any(item["id"] == str(run.id) for item in body["runs"])


@pytest.mark.asyncio
async def test_benchmark_feedback_sync_api_dry_run(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    response = await client.post(
        "/benchmark/feedback/sync",
        json={"dry_run": True, "merge_queue": False},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "queue_added" in body
    assert "sft_added" in body
    assert body["queue_path"]


@pytest.mark.asyncio
async def test_benchmark_run_not_found(client: AsyncClient):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])
    missing = uuid.uuid4()
    response = await client.get(f"/benchmark/runs/{missing}", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_benchmark_create_run_invalid_dataset_returns_404(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    response = await client.post(
        "/benchmark/runs",
        json={"dataset_name": "not_a_real_dataset"},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_benchmark_chat_send_forbidden(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    coach = User(username="coach_demo_send", password_hash="h", password_salt="s")
    db_session.add(coach)
    await db_session.flush()

    benchmark_session = ChatSession(user_id=coach.id, title="benchmark:eval-send")
    db_session.add(benchmark_session)
    await db_session.commit()

    response = await client.post(
        "/chat/send",
        headers=headers,
        json={"message": "hello", "session_id": str(benchmark_session.id)},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_benchmark_chat_stream_forbidden(client: AsyncClient, db_session):
    admin = await bootstrap_admin(client)
    headers = auth_headers(admin["access_token"])

    coach = User(username="coach_demo_stream", password_hash="h", password_salt="s")
    db_session.add(coach)
    await db_session.flush()

    benchmark_session = ChatSession(user_id=coach.id, title="benchmark:eval-stream")
    db_session.add(benchmark_session)
    await db_session.commit()

    response = await client.post(
        "/chat/stream",
        headers=headers,
        json={"message": "hello", "session_id": str(benchmark_session.id)},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_benchmark_empty_subset_marks_failed(db_session):
    from app.db.models import BenchmarkRun

    admin = User(username="bench_empty_admin", password_hash="h", password_salt="s", role="admin")
    db_session.add(admin)
    await db_session.flush()

    run = BenchmarkRun(
        dataset_name="coach_eval",
        created_by_user_id=admin.id,
        status="pending",
    )
    db_session.add(run)
    await db_session.commit()

    service = BenchmarkService()
    await service.execute_run(db_session, run.id, sample_ids=["missing-sample-id"])
    await db_session.refresh(run)

    assert run.status == "failed"
    assert run.error_message == "评测样本子集为空"
