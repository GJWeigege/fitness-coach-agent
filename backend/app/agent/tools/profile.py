from typing import Any

from app.agent.tools.base import ToolContext
from app.services.profile_service import ProfileService


class GetUserProfileTool:
    name = "get_user_profile"
    description = "读取当前用户的健身画像（身高体重、目标、伤病、设备等）。"

    def __init__(self, profile_service: ProfileService | None = None) -> None:
        self.profile_service = profile_service or ProfileService()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

    async def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict:
        profile = await self.profile_service.get_profile(ctx.db, ctx.user_id)
        return {"profile": profile.model_dump(mode="json")}
