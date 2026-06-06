import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ChatMessage, ChatSession
from app.prompts.coach_system_prompt import COACH_SYSTEM_PROMPT
from app.prompts.memory_summary_prompt import MEMORY_SUMMARY_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


@dataclass
class MemoryBuildResult:
    messages: list[dict]
    dropped_message_count: int
    memory_compacted: bool
    model_name: str | None = None


@dataclass
class SummaryUpdateResult:
    updated: bool
    summary: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    model_name: str | None = None
    latency_ms: int | None = None


class MemoryService:
    def __init__(self) -> None:
        self.settings = get_settings()

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def estimate_messages_tokens(self, messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            total += self.estimate_tokens(str(msg.get("content", "")))
        return total

    def _is_full_context_mode(self) -> bool:
        return self.settings.long_context_mode.strip().lower() == "full"

    def _resolve_model_name(self) -> str | None:
        if self._is_full_context_mode():
            return self.settings.coach_long_context_model
        return None

    def _pair_messages(
        self, all_items: list[ChatMessage]
    ) -> list[tuple[ChatMessage | None, ChatMessage | None]]:
        pairs: list[tuple[ChatMessage | None, ChatMessage | None]] = []
        pending_user: ChatMessage | None = None
        for item in all_items:
            if item.role == "user":
                pending_user = item
            elif item.role == "assistant" and pending_user is not None:
                pairs.append((pending_user, item))
                pending_user = None
            elif item.role == "assistant":
                pairs.append((None, item))
        if pending_user is not None:
            pairs.append((pending_user, None))
        return pairs

    async def build_context_messages(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        *,
        context_block: str = "",
        system_prompt: str = COACH_SYSTEM_PROMPT,
        exclude_message_id: uuid.UUID | None = None,
    ) -> MemoryBuildResult:
        session = await db.get(ChatSession, session_id)
        if session is None:
            raise ValueError("会话不存在。")

        system_parts = [system_prompt]
        if session.summary:
            system_parts.append(f"\n\n【会话摘要】\n{session.summary}")
        if context_block:
            system_parts.append(context_block)

        messages: list[dict] = [{"role": "system", "content": "".join(system_parts)}]

        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        all_items = list((await db.scalars(stmt)).all())
        if exclude_message_id:
            all_items = [m for m in all_items if m.id != exclude_message_id]

        pairs = self._pair_messages(all_items)
        full_context = self._is_full_context_mode()

        if full_context:
            selected_pairs = pairs
            dropped = 0
            compacted = False
        else:
            selected_pairs = pairs[-self.settings.memory_max_turns :]
            dropped = max(0, len(pairs) - len(selected_pairs))
            compacted = False

        for user_msg, assistant_msg in selected_pairs:
            if user_msg is not None:
                messages.append({"role": "user", "content": user_msg.content})
            if assistant_msg is not None:
                messages.append({"role": "assistant", "content": assistant_msg.content})

        if not full_context:
            while (
                len(messages) > 2
                and self.estimate_messages_tokens(messages) > self.settings.memory_max_prompt_tokens
            ):
                if messages[1]["role"] == "user":
                    messages.pop(1)
                    if len(messages) > 1 and messages[1]["role"] == "assistant":
                        messages.pop(1)
                else:
                    messages.pop(1)
                dropped += 1
                compacted = True

        return MemoryBuildResult(
            messages=messages,
            dropped_message_count=dropped,
            memory_compacted=compacted,
            model_name=self._resolve_model_name(),
        )

    async def increment_turn_count(self, db: AsyncSession, session: ChatSession) -> None:
        session.turn_count = (session.turn_count or 0) + 1
        await db.flush()

    async def maybe_update_summary(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
        llm_client,
    ) -> SummaryUpdateResult:
        session = await db.get(ChatSession, session_id)
        if session is None:
            return SummaryUpdateResult(updated=False)

        if (session.turn_count or 0) <= self.settings.memory_summary_trigger_turns:
            return SummaryUpdateResult(updated=False)

        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
        all_items = list((await db.scalars(stmt)).all())
        pairs = self._pair_messages(all_items)
        user_assistant_pairs = [
            (user_msg, assistant_msg)
            for user_msg, assistant_msg in pairs
            if user_msg is not None
        ]

        recent = user_assistant_pairs[-self.settings.memory_max_turns :]
        older = user_assistant_pairs[: max(0, len(user_assistant_pairs) - len(recent))]
        if not older:
            return SummaryUpdateResult(updated=False)

        lines: list[str] = []
        if session.summary:
            lines.append(f"已有摘要：{session.summary}")
        for user_msg, assistant_msg in older:
            lines.append(f"用户：{user_msg.content}")
            if assistant_msg:
                lines.append(f"教练：{assistant_msg.content}")

        user_content = "\n".join(lines)
        try:
            start = time.perf_counter()
            result = await llm_client.chat(
                [
                    {"role": "system", "content": MEMORY_SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": f"请更新会话摘要：\n{user_content}"},
                ],
                model=self.settings.coach_answer_model,
            )
            summary = (result.content or "").strip()[: self.settings.memory_summary_max_chars]
            if not summary:
                return SummaryUpdateResult(updated=False)
            session.summary = summary
            session.summary_updated_at = datetime.now(timezone.utc)
            await db.flush()
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.info(
                "memory_summary_updated session_id=%s latency_ms=%s",
                session_id,
                latency_ms,
            )
            return SummaryUpdateResult(
                updated=True,
                summary=summary,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                model_name=result.model_name,
                latency_ms=latency_ms,
            )
        except Exception:
            logger.exception("memory_summary_failed session_id=%s", session_id)
            return SummaryUpdateResult(updated=False)

    def validate_user_message_length(self, content: str) -> None:
        if len(content) > self.settings.memory_max_user_chars:
            raise ValueError(
                f"单条消息过长（>{self.settings.memory_max_user_chars} 字符），请分段发送。"
            )
