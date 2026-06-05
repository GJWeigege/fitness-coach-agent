from typing import Any

from sqlalchemy import select

from app.agent.tools.base import ToolContext
from app.core.config import get_settings
from app.db.models import GraphEntity
from app.services.graph_service import GraphService


class GraphLookupTool:
    name = "graph_lookup"
    description = "查询知识图谱中的实体及其一跳关联（动作、伤病、营养素等）。"

    def __init__(self, graph_service: GraphService | None = None) -> None:
        self.graph_service = graph_service or GraphService()

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "entity_name": {"type": "string", "description": "实体名称，如 深蹲"},
                        "entity_type": {
                            "type": "string",
                            "description": "实体类型，可选：exercise/injury/nutrient",
                        },
                    },
                    "required": ["entity_name"],
                },
            },
        }

    async def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict:
        settings = get_settings()
        if not settings.graph_rag_enabled:
            return {"context": None, "entities": [], "output_preview": "图谱检索已关闭"}

        name = str(arguments.get("entity_name", "")).strip()
        entity_type = arguments.get("entity_type")
        if not name:
            return {"context": None, "entities": [], "output_preview": "未提供实体名"}

        stmt = select(GraphEntity).where(GraphEntity.name.ilike(f"%{name}%"))
        if entity_type:
            stmt = stmt.where(GraphEntity.entity_type == str(entity_type))
        entity = await ctx.db.scalar(stmt.limit(1))
        if entity is None:
            return {"context": None, "entities": [], "output_preview": "未找到实体"}

        context = await self.graph_service.build_one_hop_context(ctx.db, [entity.id])
        return {
            "context": context,
            "entities": [entity.name],
            "entity_type": entity.entity_type,
            "output_preview": context[:120] if context else entity.name,
        }
