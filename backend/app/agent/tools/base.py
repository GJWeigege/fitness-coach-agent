import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ToolContext:
    db: AsyncSession
    user_id: uuid.UUID
    session_id: uuid.UUID
    message_id: uuid.UUID
    run_id: uuid.UUID
    use_rag: bool


class CoachTool(Protocol):
    name: str
    description: str

    def schema(self) -> dict: ...

    async def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict: ...
