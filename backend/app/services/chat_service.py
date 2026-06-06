import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.coach.orchestrator import CoachGraphOrchestrator, CoachRunResult
from app.agent.coach.token_usage import combined_total_tokens, merge_token_counts
from app.core.config import get_settings
from app.db.models import ChatMessage, ChatSession
from app.llm.dashscope_client import DashScopeClient
from app.services.memory_service import MemoryService
from app.services.rag_service import RagService


class ChatService:
    def __init__(self, llm_client: DashScopeClient, rag_service: RagService) -> None:
        self.llm_client = llm_client
        self.rag_service = rag_service
        self.memory_service = MemoryService()
        self.settings = get_settings()
        self.orchestrator = CoachGraphOrchestrator(
            llm_client=llm_client,
            rag_service=rag_service,
        )

    async def _apply_summary_usage(
        self,
        db: AsyncSession,
        *,
        result: CoachRunResult,
        summary_result,
    ) -> None:
        if summary_result.prompt_tokens is None and summary_result.completion_tokens is None:
            return
        result.prompt_tokens, result.completion_tokens = merge_token_counts(
            result.prompt_tokens,
            result.completion_tokens,
            summary_result.prompt_tokens,
            summary_result.completion_tokens,
        )
        await self.orchestrator.observability.record_llm_call(
            db,
            result.run_id,
            purpose="memory_summary",
            model=summary_result.model_name or self.settings.coach_answer_model,
            prompt_tokens=summary_result.prompt_tokens,
            completion_tokens=summary_result.completion_tokens,
            latency_ms=summary_result.latency_ms,
        )

    def _touch_session(self, session: ChatSession) -> None:
        session.updated_at = datetime.now(timezone.utc)

    async def _get_or_create_session(
        self,
        db: AsyncSession,
        session_id: uuid.UUID | None,
        user_id: uuid.UUID,
    ) -> ChatSession:
        if session_id:
            session = await db.get(ChatSession, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="会话不存在。")
            if session.user_id != user_id:
                raise HTTPException(status_code=403, detail="无权访问其他用户会话。")
            return session
        session = ChatSession(user_id=user_id)
        db.add(session)
        await db.flush()
        return session

    async def _persist_user_message(
        self,
        db: AsyncSession,
        session: ChatSession,
        user_message: str,
    ) -> ChatMessage:
        if session.title is None:
            session.title = user_message[:40]
        self._touch_session(session)
        self.memory_service.validate_user_message_length(user_message)
        user_record = ChatMessage(session_id=session.id, role="user", content=user_message)
        db.add(user_record)
        await self.memory_service.increment_turn_count(db, session)
        await db.flush()
        return user_record

    def _coach_result_from_event(self, event: dict) -> CoachRunResult:
        return CoachRunResult(
            run_id=uuid.UUID(event["run_id"]),
            trace_id=event["trace_id"],
            final_answer=event["final_answer"],
            citations=event.get("citations") or [],
            intent=event.get("intent") or "unknown",
            execution_plan=event.get("execution_plan"),
            cot_traces=event.get("cot_traces") or {},
            tool_calls=event.get("tool_calls") or [],
            graph_entities_used=event.get("graph_entities_used") or [],
            model_name=event.get("model_name"),
            prompt_tokens=event.get("prompt_tokens"),
            completion_tokens=event.get("completion_tokens"),
            status=event.get("status") or "completed",
            memory_compacted=bool(event.get("memory_compacted")),
            dropped_message_count=int(event.get("dropped_message_count") or 0),
            total_latency_ms=int(event.get("total_latency_ms") or 0),
            parallel_agents_used=bool(event.get("parallel_agents_used")),
        )

    async def _complete_turn_events(
        self,
        db: AsyncSession,
        *,
        session: ChatSession,
        result: CoachRunResult,
    ) -> AsyncGenerator[dict, None]:
        self._touch_session(session)
        assistant_record = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=result.final_answer,
            model_name=result.model_name,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=combined_total_tokens(result.prompt_tokens, result.completion_tokens),
            latency_ms=result.total_latency_ms,
            retrieved_chunks={"items": result.citations},
            agent_run_id=result.run_id,
        )
        db.add(assistant_record)
        await db.commit()
        await db.refresh(assistant_record)

        memory_summary_updated = False
        summary_result = await self.memory_service.maybe_update_summary(
            db, session.id, self.llm_client
        )
        if summary_result.updated:
            memory_summary_updated = True
            await self._apply_summary_usage(db, result=result, summary_result=summary_result)
            assistant_record.prompt_tokens = result.prompt_tokens
            assistant_record.completion_tokens = result.completion_tokens
            assistant_record.total_tokens = combined_total_tokens(
                result.prompt_tokens,
                result.completion_tokens,
            )
            await db.commit()

        if self.settings.agent_enable_thinking_steps:
            yield {
                "type": "step",
                "phase": "memory_summary",
                "summary": (
                    "已更新会话摘要。"
                    if memory_summary_updated
                    else "正在整理会话摘要…"
                ),
            }

        await self.orchestrator.finalize_run(
            db,
            run_id=result.run_id,
            assistant_message_id=assistant_record.id,
            memory_summary_updated=memory_summary_updated,
            result=result,
        )
        await db.commit()

        yield {
            "type": "done",
            "session_id": str(session.id),
            "run_id": str(result.run_id),
            "model_name": result.model_name or "",
            "status": result.status,
            "step_count": None,
            "latency_ms": result.total_latency_ms,
            "assistant_message_id": str(assistant_record.id),
        }

    async def _complete_turn(
        self,
        db: AsyncSession,
        *,
        session: ChatSession,
        result: CoachRunResult,
    ) -> dict:
        done_evt: dict | None = None
        async for event in self._complete_turn_events(db, session=session, result=result):
            if event.get("type") == "done":
                done_evt = event
        if done_evt is None:
            raise RuntimeError("教练回合未完成。")
        return done_evt

    async def stream_message(
        self,
        db: AsyncSession,
        user_message: str,
        user_id: uuid.UUID,
        session_id: uuid.UUID | None = None,
        use_rag: bool | None = None,
    ) -> AsyncGenerator[dict, None]:
        use_rag = self.settings.use_rag_default if use_rag is None else use_rag
        session = await self._get_or_create_session(db, session_id, user_id)
        try:
            user_record = await self._persist_user_message(db, session, user_message)
        except ValueError as exc:
            yield {"type": "error", "message": str(exc)}
            return
        await db.commit()
        await db.refresh(session)

        result: CoachRunResult | None = None
        async for event in self.orchestrator.stream_turn(
            db=db,
            session=session,
            user_record=user_record,
            user_message=user_message,
            use_rag=use_rag,
        ):
            if event.get("type") == "result":
                result = self._coach_result_from_event(event)
                continue
            if event.get("type") == "error":
                yield event
                return
            yield event

        if result is None:
            yield {"type": "error", "message": "教练未完成响应，请重试。"}
            return

        async for event in self._complete_turn_events(db, session=session, result=result):
            yield event

    async def send_message(
        self,
        db: AsyncSession,
        user_message: str,
        user_id: uuid.UUID,
        session_id: uuid.UUID | None = None,
        use_rag: bool | None = None,
    ) -> dict:
        use_rag = self.settings.use_rag_default if use_rag is None else use_rag
        session = await self._get_or_create_session(db, session_id, user_id)
        user_record = await self._persist_user_message(db, session, user_message)
        await db.commit()
        await db.refresh(session)

        chunks: list[str] = []
        citations: list[dict] = []
        result: CoachRunResult | None = None

        async for event in self.orchestrator.stream_turn(
            db=db,
            session=session,
            user_record=user_record,
            user_message=user_message,
            use_rag=use_rag,
        ):
            event_type = event.get("type")
            if event_type == "delta":
                chunks.append(event.get("content", ""))
            elif event_type == "replace":
                chunks = [event.get("content", "")]
            elif event_type == "session":
                citations = event.get("citations", [])
            elif event_type == "result":
                result = self._coach_result_from_event(event)
            elif event_type == "error":
                raise HTTPException(status_code=400, detail=event.get("message", "请求失败"))

        if result is None:
            raise HTTPException(status_code=500, detail="教练未完成响应，请重试。")

        done_evt = await self._complete_turn(db, session=session, result=result)
        reply = result.final_answer or "".join(chunks)
        return {
            "session_id": session.id,
            "reply": reply,
            "citations": citations or result.citations,
            "model_name": done_evt.get("model_name", ""),
            "run_id": uuid.UUID(done_evt["run_id"]),
            "status": done_evt.get("status", result.status),
        }
