import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coach.graph import build_coach_graph
from app.agent.coach.token_usage import token_totals
from app.agent.coach.state import CoachState, initial_coach_state
from app.agent.guardrails import CoachGuardrails
from app.agent.tools.registry import CoachToolRegistry
from app.core.config import get_settings
from app.core.errors import PUBLIC_ERROR_MESSAGE
from app.core.trace import get_trace_id
from app.db.models import AgentStep, ChatMessage, ChatSession
from app.llm.dashscope_client import DashScopeClient
from app.services.observability_service import ObservabilityService
from app.services.profile_service import ProfileService
from app.services.rag_service import RagService

logger = logging.getLogger(__name__)

SENTINEL = object()
FALLBACK_TEMPLATE = (
    "抱歉，我暂时无法完整回答您的问题。请稍后重试，或换一种方式描述您的训练/营养诉求。"
)

SKIP_STEP_NODES = frozenset(
    {
        "load_profile",
        "dispatch_sub_agents",
        "apply_guardrails",
        "persist_turn",
        "knowledge_prefetch",
        "coach_chitchat",
        "serial_dispatch",
    }
)


@dataclass
class CoachRunResult:
    run_id: uuid.UUID
    trace_id: str
    final_answer: str
    citations: list[dict]
    intent: str
    execution_plan: dict | None
    cot_traces: dict[str, str]
    tool_calls: list[dict]
    graph_entities_used: list[str]
    model_name: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    status: str
    memory_compacted: bool
    dropped_message_count: int
    total_latency_ms: int
    parallel_agents_used: bool

    def to_result_event(self) -> dict:
        payload = asdict(self)
        payload["type"] = "result"
        payload["run_id"] = str(self.run_id)
        return payload


class CoachGraphOrchestrator:
    def __init__(
        self,
        llm_client: DashScopeClient,
        rag_service: RagService,
        observability: ObservabilityService | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.rag_service = rag_service
        self.observability = observability or ObservabilityService()
        self.settings = get_settings()
        self.graph = build_coach_graph()
        self.guardrails = CoachGuardrails()

    def _step_event(
        self,
        phase: str,
        summary: str,
        *,
        step_index: int | None = None,
        agent: str | None = None,
        detail: dict | None = None,
    ) -> dict:
        evt: dict = {"type": "step", "phase": phase, "summary": summary}
        if step_index is not None:
            evt["step_index"] = step_index
        if agent:
            evt["agent"] = agent
        if detail:
            evt["detail"] = detail
        return evt

    def _maybe_step_for_node(self, node_name: str | None, node_input: dict | None) -> dict | None:
        if not node_name or node_name in SKIP_STEP_NODES:
            return None
        if node_name == "route_intent":
            return self._step_event("routing", "正在识别用户意图…")
        if node_name == "plan_execute":
            return self._step_event("planning", "正在制定执行计划…")
        if node_name == "sub_agent":
            agent = (node_input or {}).get("current_agent_key") or "training"
            return self._step_event(
                f"{agent}_agent",
                f"{agent} 子 agent 执行中",
                agent=agent,
                detail={"agent": agent},
            )
        if node_name == "safety_review":
            return self._step_event("safety_review", "安全审查")
        if node_name == "synthesize":
            return self._step_event("synthesizing", "综合建议")
        return None

    def _build_result(
        self,
        *,
        run_id: uuid.UUID,
        trace_id: str,
        final_state: CoachState,
        run_meta: dict,
        latency_ms: int,
        model_name: str | None,
    ) -> CoachRunResult:
        status = final_state.get("status") or "completed"
        final_answer = (final_state.get("final_answer") or "").strip()
        if not final_answer:
            status = "degraded"
            final_answer = FALLBACK_TEMPLATE

        prompt_tokens, completion_tokens = token_totals(run_meta)

        return CoachRunResult(
            run_id=run_id,
            trace_id=trace_id,
            final_answer=final_answer,
            citations=list(final_state.get("rag_citations") or []),
            intent=final_state.get("intent") or "unknown",
            execution_plan=final_state.get("execution_plan"),
            cot_traces=dict(final_state.get("cot_traces") or {}),
            tool_calls=list(final_state.get("tool_calls") or []),
            graph_entities_used=list(final_state.get("graph_entities_used") or []),
            model_name=model_name or self.settings.coach_answer_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            status=status,
            memory_compacted=bool(run_meta.get("memory_compacted")),
            dropped_message_count=int(run_meta.get("dropped_message_count") or 0),
            total_latency_ms=latency_ms,
            parallel_agents_used=bool(run_meta.get("parallel_agents_used")),
        )

    async def stream_turn(
        self,
        db: AsyncSession,
        *,
        session: ChatSession,
        user_record: ChatMessage,
        user_message: str,
        use_rag: bool,
    ) -> AsyncGenerator[dict, None]:
        trace_id = get_trace_id()
        start = time.perf_counter()
        run = await self.observability.create_run(
            db,
            session_id=session.id,
            user_message_id=user_record.id,
            trace_id=trace_id,
        )
        await db.commit()

        yield {"type": "run", "run_id": str(run.id), "trace_id": trace_id}

        queue: asyncio.Queue = asyncio.Queue()
        run_meta: dict = {
            "parallel_agents_used": False,
            "memory_compacted": False,
            "dropped_message_count": 0,
            "model_name": self.settings.coach_answer_model,
        }
        final_state: CoachState | None = None

        async def emit(event_type: str, data: dict) -> None:
            await queue.put({"type": event_type, **data})

        profile_service = ProfileService()
        tool_registry = CoachToolRegistry.build_default(
            self.rag_service,
            profile_service=profile_service,
        )

        init_state = initial_coach_state(
            session_id=str(session.id),
            user_id=str(session.user_id),
            user_message_id=str(user_record.id),
            user_message=user_message,
            run_id=str(run.id),
            use_rag=use_rag,
        )

        config = {
            "configurable": {
                "db": db,
                "llm": self.llm_client,
                "tool_registry": tool_registry,
                "profile_service": profile_service,
                "rag_service": self.rag_service,
                "observability": self.observability,
                "guardrails": self.guardrails,
                "emit": emit,
                "run_meta": run_meta,
            }
        }

        async def run_graph() -> CoachState:
            nonlocal final_state
            try:
                async for event in self.graph.astream_events(init_state, config, version="v2"):
                    if event.get("event") == "on_chain_start" and self.settings.agent_enable_thinking_steps:
                        node = event.get("metadata", {}).get("langgraph_node")
                        # Skip internal routing runnables (e.g. route_after_plan_execute)
                        # that share langgraph_node with the parent graph node.
                        if not node or event.get("name") != node:
                            continue
                        node_input = event.get("data", {}).get("input")
                        step_evt = self._maybe_step_for_node(node, node_input)
                        if step_evt:
                            await queue.put(step_evt)
                    if event.get("event") == "on_chain_end" and event.get("name") == "LangGraph":
                        output = event.get("data", {}).get("output")
                        if isinstance(output, dict):
                            final_state = output
                if final_state is None:
                    final_state = await self.graph.ainvoke(init_state, config)
            except Exception:
                await queue.put(SENTINEL)
                raise
            await queue.put(SENTINEL)
            return final_state or init_state

        graph_task = asyncio.create_task(run_graph())

        try:
            while True:
                if graph_task.done() and queue.empty():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.05)
                except TimeoutError:
                    continue
                if item is SENTINEL:
                    break
                yield item

            final_state = await graph_task

            yield {
                "type": "session",
                "session_id": str(session.id),
                "citations": list(final_state.get("rag_citations") or []),
            }

            latency_ms = int((time.perf_counter() - start) * 1000)
            result = self._build_result(
                run_id=run.id,
                trace_id=trace_id,
                final_state=final_state,
                run_meta=run_meta,
                latency_ms=latency_ms,
                model_name=run_meta.get("model_name"),
            )
            yield result.to_result_event()

        except ValueError as exc:
            prompt_tokens, completion_tokens = token_totals(run_meta)
            await self.observability.finish_run(
                db,
                run.id,
                status="failed",
                error_message=str(exc),
                total_latency_ms=int((time.perf_counter() - start) * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            await db.commit()
            yield {"type": "error", "message": str(exc), "trace_id": trace_id}
        except Exception as exc:
            logger.exception("coach_stream_turn_failed")
            prompt_tokens, completion_tokens = token_totals(run_meta)
            await self.observability.finish_run(
                db,
                run.id,
                status="failed",
                error_message=str(exc),
                total_latency_ms=int((time.perf_counter() - start) * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            await db.commit()
            yield {"type": "error", "message": PUBLIC_ERROR_MESSAGE, "trace_id": trace_id}

    async def finalize_run(
        self,
        db: AsyncSession,
        *,
        run_id: uuid.UUID,
        assistant_message_id: uuid.UUID,
        memory_summary_updated: bool,
        result: CoachRunResult,
    ) -> None:
        steps = list(
            (
                await db.scalars(
                    select(AgentStep)
                    .where(AgentStep.run_id == run_id)
                    .order_by(AgentStep.step_index.asc())
                )
            ).all()
        )

        planning_step = next((s for s in steps if s.phase == "planning"), None)
        if planning_step is not None and result.execution_plan is not None:
            payload = dict(planning_step.payload or {})
            payload["execution_plan"] = result.execution_plan
            payload["parallel_agents_used"] = result.parallel_agents_used
            planning_step.payload = payload
        elif result.execution_plan is not None:
            await self.observability.append_step(
                db,
                run_id,
                phase="planning",
                summary="execution plan",
                payload={
                    "execution_plan": result.execution_plan,
                    "parallel_agents_used": result.parallel_agents_used,
                },
            )

        cot_traces = self.guardrails.redact_cot_traces(result.cot_traces)

        snapshot_payload = {
            "tool_calls": result.tool_calls,
            "cot": cot_traces,
            "parallel_agents_used": result.parallel_agents_used,
            "graph_entities_used": result.graph_entities_used,
        }
        if steps:
            last = steps[-1]
            merged = dict(last.payload or {})
            merged.update(snapshot_payload)
            last.payload = merged
        else:
            await self.observability.append_step(
                db,
                run_id,
                phase="finalize",
                summary="run snapshot",
                payload=snapshot_payload,
            )

        await self.observability.finish_run(
            db,
            run_id,
            status=result.status,
            intent=result.intent,
            assistant_message_id=assistant_message_id,
            total_latency_ms=result.total_latency_ms,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            model_name=result.model_name,
            memory_compacted=result.memory_compacted,
            dropped_message_count=result.dropped_message_count,
            memory_summary_updated=memory_summary_updated,
        )
        await db.flush()
