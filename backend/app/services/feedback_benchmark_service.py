from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.guardrails import COACH_DISCLAIMER
from app.db.models import AgentRun, ChatMessage
from app.services.benchmark_runner import load_benchmark_dataset, parse_benchmark_sample

logger = logging.getLogger(__name__)

DEFAULT_BENCHMARK_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "benchmark" / "coach_eval.jsonl"
)
DEFAULT_SFT_PATH = Path(__file__).resolve().parents[2] / "data" / "finetune" / "coach_sft.jsonl"
DEFAULT_FEEDBACK_QUEUE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "benchmark" / "feedback_import.jsonl"
)

SFT_SYSTEM_PROMPT = "你是运动健康 Coach，输出 JSON plan 与带 disclaimer 的中文建议。"
FEEDBACK_SAMPLE_PREFIX = "fb-"


@dataclass
class FeedbackSyncResult:
    queue_added: int
    queue_skipped: int
    sft_added: int
    sft_skipped: int
    benchmark_path: str
    sft_path: str
    queue_path: str


def feedback_sample_id(message_id: uuid.UUID) -> str:
    return f"{FEEDBACK_SAMPLE_PREFIX}{message_id}"


def _load_jsonl_ids(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
            if row.get("id"):
                ids.add(str(row["id"]))
        except json.JSONDecodeError:
            continue
    return ids


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


async def _preceding_user_message(
    db: AsyncSession,
    assistant: ChatMessage,
) -> ChatMessage | None:
    return await db.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.session_id == assistant.session_id,
            ChatMessage.role == "user",
            or_(
                ChatMessage.created_at < assistant.created_at,
                and_(
                    ChatMessage.created_at == assistant.created_at,
                    ChatMessage.id < assistant.id,
                ),
            ),
        )
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(1)
    )


def build_benchmark_row_from_feedback(
    *,
    assistant: ChatMessage,
    user_message: ChatMessage,
    agent_run: AgentRun | None,
    feedback_rating: str,
) -> dict:
    intent = (agent_run.intent if agent_run else None) or "unknown"
    citations = assistant.retrieved_chunks or {}
    items = citations.get("items") if isinstance(citations, dict) else None
    has_citations = isinstance(items, list) and len(items) > 0

    row: dict = {
        "id": feedback_sample_id(assistant.id),
        "question": user_message.content,
        "expected_intent": intent,
        "must_cite": has_citations,
        "must_include_disclaimer": True,
        "reference_answer": assistant.content[:800],
        "feedback_source": feedback_rating,
        "feedback_message_id": str(assistant.id),
    }
    if feedback_rating == "down":
        row["review_note"] = "来自用户点踩，reference 为需改进的回复快照"
    return row


def build_sft_row_from_feedback(*, user_message: ChatMessage, assistant: ChatMessage) -> dict:
    content = assistant.content.strip()
    if COACH_DISCLAIMER not in content:
        content = f"{content}\n\n{COACH_DISCLAIMER}"
    return {
        "messages": [
            {"role": "system", "content": SFT_SYSTEM_PROMPT},
            {"role": "user", "content": user_message.content},
            {"role": "assistant", "content": content},
        ],
        "source": "feedback_up",
        "message_id": str(assistant.id),
    }


class FeedbackBenchmarkService:
    def __init__(
        self,
        *,
        benchmark_path: Path | None = None,
        sft_path: Path | None = None,
        queue_path: Path | None = None,
    ) -> None:
        self.benchmark_path = benchmark_path or DEFAULT_BENCHMARK_PATH
        self.sft_path = sft_path or DEFAULT_SFT_PATH
        self.queue_path = queue_path or DEFAULT_FEEDBACK_QUEUE_PATH

    async def sync_from_feedback(
        self,
        db: AsyncSession,
        *,
        include_down: bool = True,
        include_up: bool = True,
        dry_run: bool = False,
    ) -> FeedbackSyncResult:
        existing_benchmark_ids = _load_jsonl_ids(self.benchmark_path)
        existing_queue_ids = _load_jsonl_ids(self.queue_path)
        existing_sft_message_ids = self._load_sft_message_ids()

        assistants = list(
            (
                await db.scalars(
                    select(ChatMessage)
                    .where(
                        ChatMessage.role == "assistant",
                        ChatMessage.feedback.in_(["up", "down"]),
                    )
                    .order_by(ChatMessage.created_at.asc())
                )
            ).all()
        )

        queue_rows: list[dict] = []
        sft_rows: list[dict] = []
        queue_skipped = 0
        sft_skipped = 0

        for assistant in assistants:
            sample_id = feedback_sample_id(assistant.id)
            user_msg = await _preceding_user_message(db, assistant)
            if user_msg is None:
                continue

            agent_run = None
            if assistant.agent_run_id:
                agent_run = await db.get(AgentRun, assistant.agent_run_id)

            if assistant.feedback == "down" and include_down:
                if sample_id in existing_benchmark_ids or sample_id in existing_queue_ids:
                    queue_skipped += 1
                else:
                    row = build_benchmark_row_from_feedback(
                        assistant=assistant,
                        user_message=user_msg,
                        agent_run=agent_run,
                        feedback_rating="down",
                    )
                    queue_rows.append(row)

            if assistant.feedback == "up" and include_up:
                msg_id = str(assistant.id)
                if msg_id in existing_sft_message_ids:
                    sft_skipped += 1
                else:
                    sft_rows.append(
                        build_sft_row_from_feedback(
                            user_message=user_msg,
                            assistant=assistant,
                        )
                    )
                    existing_sft_message_ids.add(msg_id)

        if not dry_run:
            if queue_rows:
                _append_jsonl(self.queue_path, queue_rows)
            if sft_rows:
                _append_jsonl(self.sft_path, sft_rows)

        return FeedbackSyncResult(
            queue_added=len(queue_rows),
            queue_skipped=queue_skipped,
            sft_added=len(sft_rows),
            sft_skipped=sft_skipped,
            benchmark_path=str(self.benchmark_path),
            sft_path=str(self.sft_path),
            queue_path=str(self.queue_path),
        )

    def merge_feedback_queue_into_benchmark(self, *, dry_run: bool = False) -> dict:
        if not self.queue_path.is_file():
            return {"merged": 0, "skipped": 0}

        existing_ids = _load_jsonl_ids(self.benchmark_path)
        merged: list[dict] = []
        skipped = 0

        for line in self.queue_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            sample_id = str(row.get("id", ""))
            if not sample_id or sample_id in existing_ids:
                skipped += 1
                continue
            parse_benchmark_sample(row)
            merged.append(row)
            existing_ids.add(sample_id)

        if not dry_run and merged:
            _append_jsonl(self.benchmark_path, merged)

        return {"merged": len(merged), "skipped": skipped, "benchmark_path": str(self.benchmark_path)}

    def _load_sft_message_ids(self) -> set[str]:
        path = self.sft_path
        if not path.is_file():
            return set()
        ids: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
                if row.get("message_id"):
                    ids.add(str(row["message_id"]))
            except json.JSONDecodeError:
                continue
        return ids
