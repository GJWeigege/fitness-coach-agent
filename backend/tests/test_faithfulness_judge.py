import json

import pytest

from app.services.benchmark_runner import (
    BenchmarkSample,
    aggregate_benchmark_metrics,
    evaluate_sample_outcome,
)
from app.services.faithfulness_judge import FaithfulnessJudge, heuristic_faithfulness
from tests.coach_mocks import MockDashScopeClient


def test_heuristic_faithfulness_overlap():
    verdict = heuristic_faithfulness(
        reply="建议低强度训练并就医评估，仅供参考。",
        reference_answer="建议评估、替代动作、必要时就医",
    )
    assert verdict.score > 0
    assert verdict.method == "heuristic"


def test_heuristic_faithfulness_empty_reference():
    verdict = heuristic_faithfulness(reply="任意回复", reference_answer="")
    assert verdict.faithful is True
    assert verdict.method == "heuristic_empty_ref"


@pytest.mark.asyncio
async def test_llm_faithfulness_judge_parses_json():
    llm = MockDashScopeClient(chat_responses=['{"faithful": true, "score": 0.92}'])
    judge = FaithfulnessJudge(llm)
    verdict = await judge.evaluate(
        question="膝盖受伤能深蹲吗",
        reply="建议评估后再决定",
        reference_answer="建议评估、替代动作",
        use_llm=True,
    )
    assert verdict.faithful is True
    assert verdict.score == pytest.approx(0.92)
    assert verdict.method == "llm"


def test_evaluate_sample_outcome_includes_faithfulness():
    sample = BenchmarkSample(
        id="eval-f",
        question="q",
        expected_intent="safety",
        reference_answer="建议评估、替代动作",
    )
    evaluation = evaluate_sample_outcome(
        sample,
        predicted_intent="safety",
        citations=[],
        steps=[],
        reply="建议评估后再训练，仅供参考。",
        latency_ms=50,
        agent_run_id=None,
        faithfulness_verdict=heuristic_faithfulness(
            reply="建议评估后再训练，仅供参考。",
            reference_answer="建议评估、替代动作",
        ),
    )
    assert evaluation.faithfulness is not None
    assert evaluation.metrics["faithfulness_score"] is not None


def test_aggregate_benchmark_metrics_faithfulness():
    sample = BenchmarkSample(
        id="a",
        question="q",
        expected_intent="training",
        reference_answer="训练建议",
    )
    good = evaluate_sample_outcome(
        sample,
        predicted_intent="training",
        citations=[],
        steps=[],
        reply="训练建议正文",
        latency_ms=10,
        agent_run_id=None,
        faithfulness_verdict=heuristic_faithfulness(
            reply="训练建议正文",
            reference_answer="训练建议",
        ),
    )
    bad = evaluate_sample_outcome(
        sample,
        predicted_intent="training",
        citations=[],
        steps=[],
        reply="完全无关",
        latency_ms=10,
        agent_run_id=None,
        faithfulness_verdict=heuristic_faithfulness(
            reply="完全无关",
            reference_answer="训练建议",
        ),
    )
    metrics = aggregate_benchmark_metrics([good, bad])
    assert metrics["faithfulness"] == 0.5
