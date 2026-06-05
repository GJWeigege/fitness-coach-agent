from datetime import date
from typing import Any

from app.agent.tools.base import ToolContext
from app.schemas.profile import TrainingLogCreate
from app.services.profile_service import ProfileService


class LogTrainingTool:
    name = "log_training"
    description = "记录一次训练日志（日期、类型、时长、强度）。"

    def __init__(self, profile_service: ProfileService | None = None) -> None:
        self.profile_service = profile_service or ProfileService()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "session_date": {
                            "type": "string",
                            "description": "训练日期 YYYY-MM-DD",
                        },
                        "activity_type": {"type": "string", "description": "训练类型"},
                        "duration_min": {"type": "integer", "description": "时长（分钟）"},
                        "intensity": {
                            "type": "string",
                            "description": "强度，如 low/moderate/high",
                        },
                        "notes": {"type": "string", "description": "备注，可选"},
                    },
                    "required": ["session_date", "activity_type", "duration_min", "intensity"],
                },
            },
        }

    async def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict:
        raw_date = str(arguments.get("session_date", "")).strip()
        session_date = date.fromisoformat(raw_date)
        payload = TrainingLogCreate(
            session_date=session_date,
            activity_type=str(arguments.get("activity_type", "")).strip(),
            duration_min=int(arguments.get("duration_min", 0)),
            intensity=str(arguments.get("intensity", "")).strip(),
            notes=arguments.get("notes"),
        )
        item = await self.profile_service.create_training_log(ctx.db, ctx.user_id, payload)
        return {"log": item.model_dump(mode="json"), "output_preview": f"已记录 {payload.activity_type}"}
