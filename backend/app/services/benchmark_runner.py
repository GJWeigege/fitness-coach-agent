from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.guardrails import COACH_DISCLAIMER, CoachGuardrails
from app.core.config import get_settings
from app.db.models import AgentRun, AgentStep, BenchmarkResult, ChatMessage, ChatSession, User
from app.services.chat_service import ChatService
from app.services.faithfulness_judge import FaithfulnessJudge, FaithfulnessVerdict

logger = logging.getLogger(__name__)

DEFAULT_DATASET_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "benchmark" / "coach_eval.jsonl"
)
BENCHMARK_USER_USERNAME = "coach_demo"
BENCHMARK_SESSION_TITLE_PREFIX = "benchmark:"
BENCHMARK_DATASET_DIR = Path(__file__).resolve().parents[2] / "data" / "benchmark"
DISCLAIMER_MARKERS = ("仅供参考", COACH_DISCLAIMER[:12])
REQUIRED_SAMPLE_FIELDS = frozenset({"id", "question", "expected_intent"})

# Benchmark failure reason codes (also referenced by frontend formatFailureReason).
FR_INTENT_MISMATCH = "intent_mismatch"
FR_MISSING_CITATION = "missing_citation"
FR_MISSING_DISCLAIMER = "missing_disclaimer"
FR_BANNED_DIAGNOSIS = "banned_diagnosis"
FR_MISSING_SAFETY_REVIEW = "missing_safety_review"
FR_UNFAITHFUL_ANSWER = "unfaithful_answer"
FR_RUN_ERROR = "run_error"
FR_MISSING_TOOLS_PREFIX = "missing_tools:"
FR_PLAN_AGENTS_MISMATCH_PREFIX = "plan_agents_mismatch:"


def missing_tools_reason(missing: list[str]) -> str:
    return f"{FR_MISSING_TOOLS_PREFIX}{','.join(missing)}"


def plan_agents_mismatch_reason(*, expected: list[str], actual: list[str]) -> str:
    return (
        f"{FR_PLAN_AGENTS_MISMATCH_PREFIX}"
        f"expected={','.join(expected)},actual={','.join(actual)}"
    )


@dataclass
class BenchmarkSample:
    id: str
    question: str
    expected_intent: str
    expected_plan_agents: list[str] = field(default_factory=list)
    must_cite: bool = False
    must_include_tools: list[str] = field(default_factory=list)
    must_include_disclaimer: bool = False
    reference_answer: str | None = None


@dataclass
class RunEvaluation:
    sample_id: str
    question: str
    expected_intent: str
    predicted_intent: str | None
    agent_run_id: uuid.UUID | None
    latency_ms: int | None
    intent_match: bool
    plan_agent_recall: float | None
    cited: bool
    tools_covered: bool | None
    safety_compliant: bool | None
    faithfulness: bool | None
    faithfulness_score: float | None
    passed: bool
    metrics: dict


def is_benchmark_chat_session(session: ChatSession) -> bool:
    title = session.title or ""
    return title.startswith(BENCHMARK_SESSION_TITLE_PREFIX)


def resolve_dataset_path(dataset_name: str) -> Path:
    if dataset_name == "coach_eval":
        return DEFAULT_DATASET_PATH
    candidate = Path(dataset_name)
    if ".." in candidate.parts:
        raise FileNotFoundError(f"benchmark dataset not found: {dataset_name}")
    if not candidate.is_absolute():
        candidate = BENCHMARK_DATASET_DIR / candidate
    try:
        resolved = candidate.resolve(strict=True)
        benchmark_root = BENCHMARK_DATASET_DIR.resolve()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"benchmark dataset not found: {dataset_name}") from exc
    if benchmark_root not in resolved.parents and resolved != benchmark_root:
        raise FileNotFoundError(f"benchmark dataset not found: {dataset_name}")
    if not resolved.is_file():
        raise FileNotFoundError(f"benchmark dataset not found: {dataset_name}")
    return resolved


def parse_benchmark_sample(raw: dict) -> BenchmarkSample:
    missing = REQUIRED_SAMPLE_FIELDS - set(raw)
    if missing:
        raise ValueError(f"sample missing fields: {sorted(missing)}")

    expected_intent = str(raw["expected_intent"]).strip()
    plan_agents = raw.get("expected_plan_agents") or []
    tools = raw.get("must_include_tools") or []

    return BenchmarkSample(
        id=str(raw["id"]),
        question=str(raw["question"]),
        expected_intent=expected_intent,
        expected_plan_agents=[str(a) for a in plan_agents],
        must_cite=bool(raw.get("must_cite", False)),
        must_include_tools=[str(t) for t in tools],
        must_include_disclaimer=bool(raw.get("must_include_disclaimer", False)),
        reference_answer=raw.get("reference_answer"),
    )


def select_benchmark_samples(
    samples: list[BenchmarkSample],
    *,
    limit: int | None = None,
    sample_ids: list[str] | None = None,
) -> list[BenchmarkSample]:
    if sample_ids:
        by_id = {sample.id: sample for sample in samples}
        selected: list[BenchmarkSample] = []
        for sample_id in sample_ids:
            match = by_id.get(sample_id)
            if match is None:
                logger.warning("benchmark sample_id not found: %s", sample_id)
                continue
            selected.append(match)
        return selected
    if limit is not None:
        return samples[:limit]
    return samples


def load_benchmark_dataset(path: Path | str | None = None) -> list[BenchmarkSample]:
    dataset_path = Path(path) if path else DEFAULT_DATASET_PATH
    if not dataset_path.is_file():
        raise FileNotFoundError(f"benchmark dataset not found: {dataset_path}")

    samples: list[BenchmarkSample] = []
    for line_no, line in enumerate(dataset_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
            samples.append(parse_benchmark_sample(raw))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise ValueError(f"invalid sample at line {line_no}: {exc}") from exc
    return samples


def extract_plan_agents(steps: list[AgentStep]) -> set[str]:
    planning = next((s for s in steps if s.phase == "planning"), None)
    if planning is None or not planning.payload:
        return set()

    payload = planning.payload
    plan = payload.get("execution_plan") if isinstance(payload, dict) else None
    if not isinstance(plan, dict):
        return set()

    agents: set[str] = set()
    for task in plan.get("tasks") or []:
        if isinstance(task, dict) and task.get("agent"):
            agents.add(str(task["agent"]))
    return agents


def extract_tool_names(steps: list[AgentStep]) -> set[str]:
    names: set[str] = set()
    for step in steps:
        payload = step.payload or {}
        for tc in payload.get("tool_calls") or []:
            if isinstance(tc, dict) and tc.get("name"):
                names.add(str(tc["name"]))
    return names


def has_safety_review_step(steps: list[AgentStep]) -> bool:
    return any(s.phase == "safety_review" for s in steps)


def reply_has_disclaimer(text: str) -> bool:
    if not text:
        return False
    return any(marker in text for marker in DISCLAIMER_MARKERS)


def compute_plan_agent_recall(expected: list[str], actual: set[str]) -> float | None:
    if not expected:
        return None
    expected_set = set(expected)
    if not expected_set:
        return None
    covered = len(expected_set & actual)
    return covered / len(expected_set)


def compute_tools_covered(required: list[str], actual: set[str]) -> bool | None:
    if not required:
        return None
    return set(required).issubset(actual)


def compute_safety_compliance(
    *,
    must_include_disclaimer: bool,
    reply: str,
    predicted_intent: str | None,
    steps: list[AgentStep],
    guardrails: CoachGuardrails | None = None,
) -> bool | None:
    if not must_include_disclaimer:
        return None
    g = guardrails or CoachGuardrails()
    has_disclaimer = reply_has_disclaimer(reply)
    no_banned = not g.contains_banned_diagnosis(reply)
    safety_ok = predicted_intent == "safety" or has_safety_review_step(steps)
    return has_disclaimer and no_banned and safety_ok


def collect_failure_reasons(
    sample: BenchmarkSample,
    *,
    predicted_intent: str | None,
    citations: list,
    steps: list[AgentStep],
    reply: str,
    guardrails: CoachGuardrails | None = None,
    faithfulness: bool | None = None,
) -> list[str]:
    reasons: list[str] = []
    plan_agents = extract_plan_agents(steps)
    tool_names = extract_tool_names(steps)

    if predicted_intent != sample.expected_intent:
        reasons.append(FR_INTENT_MISMATCH)

    if sample.must_cite and len(citations) == 0:
        reasons.append(FR_MISSING_CITATION)

    if sample.must_include_tools:
        required = set(sample.must_include_tools)
        if not required.issubset(tool_names):
            missing = sorted(required - tool_names)
            reasons.append(missing_tools_reason(missing))

    if sample.expected_plan_agents:
        recall = compute_plan_agent_recall(sample.expected_plan_agents, plan_agents)
        if recall is None or recall < 1.0:
            expected = sorted(set(sample.expected_plan_agents))
            actual = sorted(plan_agents)
            reasons.append(plan_agents_mismatch_reason(expected=expected, actual=actual))

    if sample.must_include_disclaimer:
        g = guardrails or CoachGuardrails()
        if not reply_has_disclaimer(reply):
            reasons.append(FR_MISSING_DISCLAIMER)
        elif g.contains_banned_diagnosis(reply):
            reasons.append(FR_BANNED_DIAGNOSIS)
        elif predicted_intent != "safety" and not has_safety_review_step(steps):
            reasons.append(FR_MISSING_SAFETY_REVIEW)

    if faithfulness is False:
        reasons.append(FR_UNFAITHFUL_ANSWER)

    return reasons


def evaluate_sample_outcome(
    sample: BenchmarkSample,
    *,
    predicted_intent: str | None,
    citations: list,
    steps: list[AgentStep],
    reply: str,
    latency_ms: int | None,
    agent_run_id: uuid.UUID | None,
    guardrails: CoachGuardrails | None = None,
    faithfulness_verdict: FaithfulnessVerdict | None = None,
) -> RunEvaluation:
    plan_agents = extract_plan_agents(steps)
    tool_names = extract_tool_names(steps)

    intent_match = predicted_intent == sample.expected_intent
    plan_recall = compute_plan_agent_recall(sample.expected_plan_agents, plan_agents)
    cited = len(citations) > 0
    tools_ok = compute_tools_covered(sample.must_include_tools, tool_names)
    safety_ok = compute_safety_compliance(
        must_include_disclaimer=sample.must_include_disclaimer,
        reply=reply,
        predicted_intent=predicted_intent,
        steps=steps,
        guardrails=guardrails,
    )

    checks: list[bool] = [intent_match]
    if sample.must_cite:
        checks.append(cited)
    if sample.must_include_tools:
        checks.append(bool(tools_ok))
    if sample.must_include_disclaimer:
        checks.append(bool(safety_ok))
    if sample.expected_plan_agents:
        checks.append(plan_recall is not None and plan_recall >= 1.0)

    faithfulness: bool | None = None
    faithfulness_score: float | None = None
    if sample.reference_answer and faithfulness_verdict is not None:
        if faithfulness_verdict.method != "skipped_no_reference":
            faithfulness = faithfulness_verdict.faithful
            faithfulness_score = faithfulness_verdict.score

    if faithfulness is not None:
        checks.append(faithfulness)

    failure_reasons = collect_failure_reasons(
        sample,
        predicted_intent=predicted_intent,
        citations=citations,
        steps=steps,
        reply=reply,
        guardrails=guardrails,
        faithfulness=faithfulness,
    )

    metrics = {
        "intent_match": intent_match,
        "plan_agent_recall": plan_recall,
        "cited": cited if sample.must_cite else None,
        "tools_covered": tools_ok,
        "safety_compliant": safety_ok,
        "faithfulness": faithfulness,
        "faithfulness_score": faithfulness_score,
        "faithfulness_method": (
            faithfulness_verdict.method if faithfulness_verdict is not None else None
        ),
        "latency_ms": latency_ms,
        "plan_agents": sorted(plan_agents),
        "tool_names": sorted(tool_names),
        "failure_reasons": failure_reasons,
    }

    return RunEvaluation(
        sample_id=sample.id,
        question=sample.question,
        expected_intent=sample.expected_intent,
        predicted_intent=predicted_intent,
        agent_run_id=agent_run_id,
        latency_ms=latency_ms,
        intent_match=intent_match,
        plan_agent_recall=plan_recall,
        cited=cited,
        tools_covered=tools_ok,
        safety_compliant=safety_ok,
        faithfulness=faithfulness,
        faithfulness_score=faithfulness_score,
        passed=all(checks),
        metrics=metrics,
    )


def aggregate_benchmark_metrics(evaluations: list[RunEvaluation]) -> dict:
    if not evaluations:
        return {
            "sample_count": 0,
            "intent_accuracy": 0.0,
            "plan_agent_recall": None,
            "citation_rate": None,
            "tool_recall": None,
            "safety_compliance": None,
            "faithfulness": None,
            "latency_p95_ms": None,
            "recovery_latency_p95_ms": None,
            "passed_count": 0,
        }

    intent_hits = sum(1 for e in evaluations if e.intent_match)
    intent_accuracy = intent_hits / len(evaluations)

    plan_samples = [e for e in evaluations if e.plan_agent_recall is not None]
    plan_agent_recall = (
        sum(e.plan_agent_recall or 0.0 for e in plan_samples) / len(plan_samples)
        if plan_samples
        else None
    )

    cite_samples = [e for e in evaluations if e.metrics.get("cited") is not None]
    citation_rate = (
        sum(1 for e in cite_samples if e.cited) / len(cite_samples) if cite_samples else None
    )

    tool_samples = [e for e in evaluations if e.tools_covered is not None]
    tool_recall = (
        sum(1 for e in tool_samples if e.tools_covered) / len(tool_samples)
        if tool_samples
        else None
    )

    safety_samples = [e for e in evaluations if e.safety_compliant is not None]
    safety_compliance = (
        sum(1 for e in safety_samples if e.safety_compliant) / len(safety_samples)
        if safety_samples
        else None
    )

    latencies = sorted(e.latency_ms for e in evaluations if e.latency_ms is not None)
    latency_p95_ms = percentile(latencies, 95) if latencies else None

    recovery_latencies = sorted(
        e.latency_ms
        for e in evaluations
        if e.latency_ms is not None and e.expected_intent == "recovery"
    )
    recovery_latency_p95_ms = (
        percentile(recovery_latencies, 95) if recovery_latencies else None
    )

    faithfulness_samples = [e for e in evaluations if e.faithfulness is not None]
    faithfulness_rate = (
        sum(1 for e in faithfulness_samples if e.faithfulness) / len(faithfulness_samples)
        if faithfulness_samples
        else None
    )

    return {
        "sample_count": len(evaluations),
        "intent_accuracy": round(intent_accuracy, 4),
        "plan_agent_recall": round(plan_agent_recall, 4) if plan_agent_recall is not None else None,
        "citation_rate": round(citation_rate, 4) if citation_rate is not None else None,
        "tool_recall": round(tool_recall, 4) if tool_recall is not None else None,
        "safety_compliance": round(safety_compliance, 4) if safety_compliance is not None else None,
        "faithfulness": round(faithfulness_rate, 4) if faithfulness_rate is not None else None,
        "latency_p95_ms": latency_p95_ms,
        "recovery_latency_p95_ms": recovery_latency_p95_ms,
        "passed_count": sum(1 for e in evaluations if e.passed),
    }


def percentile(sorted_values: list[int], p: int) -> int | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = max(0, min(len(sorted_values) - 1, int(round((p / 100.0) * (len(sorted_values) - 1)))))
    return sorted_values[rank]


class BenchmarkRunner:
    def __init__(
        self,
        chat_service: ChatService,
        *,
        faithfulness_judge: FaithfulnessJudge | None = None,
        enable_faithfulness_judge: bool = True,
    ) -> None:
        self.chat_service = chat_service
        self.guardrails = CoachGuardrails()
        self.faithfulness_judge = faithfulness_judge or FaithfulnessJudge(
            chat_service.llm_client
        )
        self.enable_faithfulness_judge = enable_faithfulness_judge

    async def _cleanup_benchmark_session(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> None:
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
        await db.execute(delete(AgentRun).where(AgentRun.session_id == session_id))
        await db.execute(delete(ChatSession).where(ChatSession.id == session_id))

    async def resolve_benchmark_user(self, db: AsyncSession) -> User:
        user = await db.scalar(select(User).where(User.username == BENCHMARK_USER_USERNAME))
        if user is None:
            raise RuntimeError(f"benchmark user '{BENCHMARK_USER_USERNAME}' not found")
        return user

    async def run_sample(
        self,
        db: AsyncSession,
        sample: BenchmarkSample,
        *,
        user_id: uuid.UUID,
    ) -> RunEvaluation:
        session = ChatSession(
            user_id=user_id,
            title=f"{BENCHMARK_SESSION_TITLE_PREFIX}{sample.id}",
        )
        db.add(session)
        await db.flush()
        session_id = session.id

        try:
            result = await self.chat_service.send_message(
                db,
                user_message=sample.question,
                user_id=user_id,
                session_id=session.id,
            )
        except Exception:
            logger.exception("benchmark_sample_failed sample_id=%s", sample.id)
            await self._cleanup_benchmark_session(db, session_id)
            return RunEvaluation(
                sample_id=sample.id,
                question=sample.question,
                expected_intent=sample.expected_intent,
                predicted_intent=None,
                agent_run_id=None,
                latency_ms=None,
                intent_match=False,
                plan_agent_recall=None,
                cited=False,
                tools_covered=False if sample.must_include_tools else None,
                safety_compliant=False if sample.must_include_disclaimer else None,
                faithfulness=None,
                faithfulness_score=None,
                passed=False,
                metrics={"error": True, "failure_reasons": [FR_RUN_ERROR]},
            )

        run_id = result["run_id"]
        agent_run = await db.get(AgentRun, run_id)
        steps = list(
            (
                await db.scalars(
                    select(AgentStep)
                    .where(AgentStep.run_id == run_id)
                    .order_by(AgentStep.step_index.asc())
                )
            ).all()
        )
        assistant = None
        if agent_run and agent_run.assistant_message_id:
            assistant = await db.get(ChatMessage, agent_run.assistant_message_id)

        citations: list = []
        if assistant and assistant.retrieved_chunks:
            items = assistant.retrieved_chunks.get("items")
            if isinstance(items, list):
                citations = items
        if not citations:
            citations = list(result.get("citations") or [])

        reply = assistant.content if assistant else str(result.get("reply") or "")
        predicted_intent = agent_run.intent if agent_run else None
        latency_ms = agent_run.total_latency_ms if agent_run else None

        faithfulness_verdict: FaithfulnessVerdict | None = None
        if self.enable_faithfulness_judge and sample.reference_answer:
            settings = get_settings()
            faithfulness_verdict = await self.faithfulness_judge.evaluate(
                question=sample.question,
                reply=reply,
                reference_answer=sample.reference_answer,
                use_llm=settings.benchmark_faithfulness_use_llm,
            )

        evaluation = evaluate_sample_outcome(
            sample,
            predicted_intent=predicted_intent,
            citations=citations,
            steps=steps,
            reply=reply,
            latency_ms=latency_ms,
            agent_run_id=run_id,
            guardrails=self.guardrails,
            faithfulness_verdict=faithfulness_verdict,
        )
        await self._cleanup_benchmark_session(db, session_id)
        return evaluation

    async def run_dataset(
        self,
        db: AsyncSession,
        samples: list[BenchmarkSample],
        *,
        user_id: uuid.UUID | None = None,
        should_cancel: Callable[[], bool | Awaitable[bool]] | None = None,
        on_sample: Callable[[RunEvaluation], Awaitable[None]] | None = None,
    ) -> list[RunEvaluation]:
        if user_id is None:
            user_id = (await self.resolve_benchmark_user(db)).id
        evaluations: list[RunEvaluation] = []
        for sample in samples:
            if should_cancel is not None:
                cancelled = should_cancel()
                if isinstance(cancelled, Awaitable):
                    cancelled = await cancelled
                if cancelled:
                    break
            evaluation = await self.run_sample(db, sample, user_id=user_id)
            evaluations.append(evaluation)
            if on_sample is not None:
                await on_sample(evaluation)
        return evaluations


def evaluation_to_benchmark_result(
    run_id: uuid.UUID,
    evaluation: RunEvaluation,
) -> BenchmarkResult:
    return BenchmarkResult(
        run_id=run_id,
        sample_id=evaluation.sample_id,
        question=evaluation.question,
        expected_intent=evaluation.expected_intent,
        predicted_intent=evaluation.predicted_intent,
        passed=evaluation.passed,
        metrics=evaluation.metrics,
        agent_run_id=evaluation.agent_run_id,
    )
