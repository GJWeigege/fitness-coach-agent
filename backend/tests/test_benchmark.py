import json
import uuid

import pytest
from sqlalchemy import select

from app.agent.guardrails import COACH_DISCLAIMER, CoachGuardrails
from app.db.models import AgentStep, User
from app.services.benchmark_runner import (
    DEFAULT_DATASET_PATH,
    FR_INTENT_MISMATCH,
    FR_MISSING_CITATION,
    FR_MISSING_DISCLAIMER,
    FR_MISSING_SAFETY_REVIEW,
    FR_MISSING_TOOLS_PREFIX,
    BenchmarkRunner,
    BenchmarkSample,
    aggregate_benchmark_metrics,
    collect_failure_reasons,
    compute_plan_agent_recall,
    compute_safety_compliance,
    evaluate_sample_outcome,
    extract_plan_agents,
    extract_tool_names,
    load_benchmark_dataset,
    parse_benchmark_sample,
    percentile,
    resolve_dataset_path,
    select_benchmark_samples,
)
from app.services.chat_service import ChatService
from app.services.faithfulness_judge import heuristic_faithfulness
from app.services.rag_service import RagService
from tests.coach_mocks import MockDashScopeClient


def _step(phase: str, payload: dict | None, step_index: int = 0) -> AgentStep:
    return AgentStep(
        run_id=uuid.uuid4(),
        step_index=step_index,
        phase=phase,
        summary=phase,
        payload=payload,
        status="completed",
    )


def test_dataset_has_minimum_samples_and_required_fields():
    samples = load_benchmark_dataset(DEFAULT_DATASET_PATH)
    assert len(samples) >= 80
    for sample in samples:
        assert sample.id
        assert sample.question
        assert sample.expected_intent


def test_resolve_dataset_path_rejects_outside_benchmark_dir():
    with pytest.raises(FileNotFoundError):
        resolve_dataset_path("../../.env")


def test_select_benchmark_samples_limit():
    samples = load_benchmark_dataset(DEFAULT_DATASET_PATH)
    subset = select_benchmark_samples(samples, limit=10)
    assert len(subset) == 10
    assert subset[0].id == samples[0].id


def test_benchmark_create_request_rejects_both_subset_options():
    from pydantic import ValidationError

    from app.schemas.benchmark import BenchmarkRunCreateRequest

    with pytest.raises(ValidationError, match="sample_limit"):
        BenchmarkRunCreateRequest(sample_limit=10, sample_ids=["eval-001"])


def test_benchmark_create_request_rejects_empty_sample_ids():
    from pydantic import ValidationError

    from app.schemas.benchmark import BenchmarkRunCreateRequest

    with pytest.raises(ValidationError, match="sample_ids"):
        BenchmarkRunCreateRequest(sample_ids=[])


def test_select_benchmark_samples_by_ids():
    samples = load_benchmark_dataset(DEFAULT_DATASET_PATH)
    picked = select_benchmark_samples(samples, sample_ids=[samples[0].id, samples[2].id])
    assert [sample.id for sample in picked] == [samples[0].id, samples[2].id]


def test_parse_benchmark_sample_with_plan_agents():
    raw = {
        "id": "eval-x",
        "question": "恢复计划",
        "expected_intent": "recovery",
        "expected_plan_agents": ["training", "nutrition"],
        "must_cite": True,
        "must_include_tools": ["knowledge_search"],
        "must_include_disclaimer": True,
    }
    sample = parse_benchmark_sample(raw)
    assert sample.expected_plan_agents == ["training", "nutrition"]
    assert sample.must_include_tools == ["knowledge_search"]


def test_extract_plan_agents_from_planning_step():
    steps = [
        _step(
            "planning",
            {
                "execution_plan": {
                    "tasks": [{"agent": "training"}, {"agent": "nutrition"}],
                }
            },
        )
    ]
    assert extract_plan_agents(steps) == {"training", "nutrition"}


def test_extract_tool_names_from_last_step_payload():
    steps = [
        _step(
            "finalize",
            {"tool_calls": [{"name": "knowledge_search"}, {"name": "calculate_macros"}]},
        )
    ]
    assert extract_tool_names(steps) == {"knowledge_search", "calculate_macros"}


def test_compute_plan_agent_recall_partial():
    assert compute_plan_agent_recall(["training", "nutrition"], {"training"}) == 0.5
    assert compute_plan_agent_recall(["training"], {"training"}) == 1.0
    assert compute_plan_agent_recall([], {"training"}) is None


def test_compute_safety_compliance_requires_disclaimer_and_no_banned():
    reply = f"建议低强度训练。\n\n{COACH_DISCLAIMER}"
    steps = [_step("safety_review", {})]
    assert (
        compute_safety_compliance(
            must_include_disclaimer=True,
            reply=reply,
            predicted_intent="safety",
            steps=steps,
        )
        is True
    )


def test_evaluate_sample_outcome_passes_when_all_criteria_met():
    sample = BenchmarkSample(
        id="eval-001",
        question="膝盖受伤",
        expected_intent="safety",
        expected_plan_agents=[],
        must_cite=True,
        must_include_tools=["check_contraindication"],
        must_include_disclaimer=True,
    )
    steps = [
        _step("safety_review", {}),
        _step("finalize", {"tool_calls": [{"name": "check_contraindication"}]}),
    ]
    evaluation = evaluate_sample_outcome(
        sample,
        predicted_intent="safety",
        citations=[{"chunk_id": "c1"}],
        steps=steps,
        reply=f"建议评估。\n\n{COACH_DISCLAIMER}",
        latency_ms=120,
        agent_run_id=uuid.uuid4(),
    )
    assert evaluation.passed is True
    assert evaluation.intent_match is True
    assert evaluation.tools_covered is True
    assert evaluation.safety_compliant is True
    assert evaluation.metrics["failure_reasons"] == []


def test_collect_failure_reasons_for_intent_and_safety():
    sample = BenchmarkSample(
        id="eval-003",
        question="增肌训练",
        expected_intent="training",
        must_cite=True,
        must_include_tools=["knowledge_search"],
        must_include_disclaimer=True,
    )
    reasons = collect_failure_reasons(
        sample,
        predicted_intent="training",
        citations=[],
        steps=[],
        reply="无免责声明",
    )
    assert FR_MISSING_CITATION in reasons
    assert f"{FR_MISSING_TOOLS_PREFIX}knowledge_search" in reasons
    assert FR_MISSING_DISCLAIMER in reasons

    reasons_with_disclaimer = collect_failure_reasons(
        BenchmarkSample(
            id="eval-003",
            question="增肌训练",
            expected_intent="training",
            must_include_disclaimer=True,
        ),
        predicted_intent="training",
        citations=[{"chunk_id": "c1"}],
        steps=[],
        reply=f"训练建议。\n\n{COACH_DISCLAIMER}",
    )
    assert reasons_with_disclaimer == [FR_MISSING_SAFETY_REVIEW]


def test_evaluate_sample_outcome_includes_failure_reasons_when_failed():
    sample = BenchmarkSample(
        id="eval-008",
        question="硬拉腰疼",
        expected_intent="safety",
        must_cite=True,
        must_include_disclaimer=True,
    )
    evaluation = evaluate_sample_outcome(
        sample,
        predicted_intent="training",
        citations=[{"chunk_id": "c1"}],
        steps=[],
        reply=f"训练建议。\n\n{COACH_DISCLAIMER}",
        latency_ms=100,
        agent_run_id=uuid.uuid4(),
    )
    assert evaluation.passed is False
    assert FR_INTENT_MISMATCH in evaluation.metrics["failure_reasons"]
    assert FR_MISSING_SAFETY_REVIEW in evaluation.metrics["failure_reasons"]


def test_faithfulness_affects_passed_when_reference_present():
    from app.services.faithfulness_judge import FaithfulnessVerdict

    sample = BenchmarkSample(
        id="faith-1",
        question="如何训练",
        expected_intent="training",
        reference_answer="循序渐进训练",
    )
    faithful = evaluate_sample_outcome(
        sample,
        predicted_intent="training",
        citations=[],
        steps=[],
        reply="循序渐进训练建议",
        latency_ms=100,
        agent_run_id=uuid.uuid4(),
        faithfulness_verdict=FaithfulnessVerdict(
            faithful=True,
            score=0.9,
            method="heuristic",
        ),
    )
    unfaithful = evaluate_sample_outcome(
        sample,
        predicted_intent="training",
        citations=[],
        steps=[],
        reply="完全无关的回答",
        latency_ms=100,
        agent_run_id=uuid.uuid4(),
        faithfulness_verdict=FaithfulnessVerdict(
            faithful=False,
            score=0.1,
            method="heuristic",
        ),
    )
    assert faithful.passed is True
    assert unfaithful.passed is False


def test_benchmark_error_message_sanitizes_internal_errors():
    from app.core.errors import PUBLIC_ERROR_MESSAGE
    from app.services.benchmark_service import benchmark_error_message

    assert benchmark_error_message(ValueError("评测样本子集为空")) == "评测样本子集为空"
    assert benchmark_error_message(RuntimeError("secret db path /var/lib")) == PUBLIC_ERROR_MESSAGE


def test_aggregate_benchmark_metrics():
    evaluations = [
        evaluate_sample_outcome(
            BenchmarkSample(
                id="a",
                question="q",
                expected_intent="training",
                must_cite=True,
                must_include_tools=["knowledge_search"],
                must_include_disclaimer=True,
            ),
            predicted_intent="training",
            citations=[{"x": 1}],
            steps=[
                _step("safety_review", {}),
                _step("finalize", {"tool_calls": [{"name": "knowledge_search"}]}),
            ],
            reply=f"训练建议。\n\n{COACH_DISCLAIMER}",
            latency_ms=100,
            agent_run_id=uuid.uuid4(),
        ),
        evaluate_sample_outcome(
            BenchmarkSample(
                id="b",
                question="q2",
                expected_intent="recovery",
                expected_plan_agents=["training", "nutrition"],
                must_cite=True,
                must_include_disclaimer=True,
            ),
            predicted_intent="nutrition",
            citations=[],
            steps=[
                _step(
                    "planning",
                    {"execution_plan": {"tasks": [{"agent": "training"}]}},
                )
            ],
            reply="无 disclaimer",
            latency_ms=200,
            agent_run_id=uuid.uuid4(),
        ),
    ]
    metrics = aggregate_benchmark_metrics(evaluations)
    assert metrics["sample_count"] == 2
    assert metrics["intent_accuracy"] == 0.5
    assert metrics["plan_agent_recall"] == 0.5
    assert metrics["citation_rate"] == 0.5
    assert metrics["tool_recall"] == 1.0
    assert metrics["safety_compliance"] == 0.5
    assert metrics["latency_p95_ms"] == 200
    assert metrics["recovery_latency_p95_ms"] == 200


def test_percentile_single_value():
    assert percentile([42], 95) == 42
    assert percentile([10, 20, 30, 40, 100], 95) == 100


def test_mock_benchmark_aggregate_meets_thresholds():
    from app.agent.guardrails import COACH_DISCLAIMER

    disclaimer_reply = f"训练与营养建议。\n\n{COACH_DISCLAIMER}"
    perfect = [
        evaluate_sample_outcome(
            BenchmarkSample(
                id=f"eval-{i:03d}",
                question="q",
                expected_intent="recovery" if i % 5 == 0 else "training",
                expected_plan_agents=["training", "nutrition"] if i % 5 == 0 else [],
                must_cite=True,
                must_include_tools=["knowledge_search"] if i % 3 == 0 else [],
                must_include_disclaimer=True,
                reference_answer="训练建议",
            ),
            predicted_intent="recovery" if i % 5 == 0 else "training",
            citations=[{"chunk_id": "c1"}],
            steps=[
                _step("safety_review", {}),
                _step(
                    "planning",
                    {
                        "execution_plan": {
                            "tasks": [{"agent": "training"}, {"agent": "nutrition"}],
                        }
                    },
                ),
                _step("finalize", {"tool_calls": [{"name": "knowledge_search"}]}),
            ],
            reply=disclaimer_reply,
            latency_ms=100 + i,
            agent_run_id=uuid.uuid4(),
            faithfulness_verdict=heuristic_faithfulness(
                reply=disclaimer_reply, reference_answer="训练建议"
            ),
        )
        for i in range(80)
    ]
    metrics = aggregate_benchmark_metrics(perfect)
    assert metrics["sample_count"] == 80
    assert metrics["intent_accuracy"] >= 0.75
    assert metrics["plan_agent_recall"] >= 0.70
    assert metrics["citation_rate"] >= 0.70
    assert metrics["tool_recall"] >= 0.65
    assert metrics["safety_compliance"] >= 0.90
    assert metrics["latency_p95_ms"] <= 8000
    assert metrics["faithfulness"] is not None


@pytest.fixture
def benchmark_settings(monkeypatch):
    from app.core.config import Settings

    settings = Settings(
        dashscope_api_key="test-key",
        sub_agent_max_tool_steps=2,
        cot_enabled=False,
        parallel_sub_agents_enabled=True,
        max_sub_agents_per_turn=2,
        memory_max_turns=8,
        memory_max_prompt_tokens=12000,
        long_context_mode="summary",
        graph_rag_enabled=False,
        agent_enable_thinking_steps=False,
        memory_summary_trigger_turns=999,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    for mod in (
        "app.services.chat_service",
        "app.agent.coach.orchestrator",
        "app.agent.coach.nodes.sub_agent",
        "app.agent.coach.nodes.plan_execute",
        "app.agent.coach.nodes.dispatch_sub_agents",
        "app.agent.coach.nodes.synthesize",
        "app.agent.tools.registry",
        "app.services.memory_service",
    ):
        monkeypatch.setattr(f"{mod}.get_settings", lambda: settings)
    return settings


@pytest.mark.asyncio
async def test_benchmark_runner_single_sample_with_mock_llm(db_session, benchmark_settings):
    user = User(username="coach_demo", password_hash="h", password_salt="s")
    db_session.add(user)
    await db_session.flush()

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
    rag = RagService(llm_client=llm)
    chat = ChatService(llm_client=llm, rag_service=rag)
    runner = BenchmarkRunner(chat)

    sample = BenchmarkSample(
        id="mock-001",
        question="我想力量训练增肌",
        expected_intent="training",
        must_cite=False,
        must_include_disclaimer=False,
    )
    evaluation = await runner.run_sample(db_session, sample, user_id=user.id)
    await db_session.commit()

    assert evaluation.predicted_intent == "training"
    assert evaluation.agent_run_id is not None
    assert evaluation.latency_ms is not None

    runs = list((await db_session.scalars(select(User))).all())
    assert any(u.username == "coach_demo" for u in runs)
