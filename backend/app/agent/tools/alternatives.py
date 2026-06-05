from typing import Any

from sqlalchemy import select

from app.agent.tools.base import ToolContext
from app.db.models import GraphEdge, GraphEntity


class SuggestAlternativesTool:
    name = "suggest_alternatives"
    description = "基于伤病、设备限制或动作禁忌，推荐替代训练动作。"

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "exercise": {"type": "string", "description": "原动作名称"},
                        "injury_or_limit": {
                            "type": "string",
                            "description": "伤病或限制，可选",
                        },
                        "equipment": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "可用设备，可选",
                        },
                    },
                    "required": ["exercise"],
                },
            },
        }

    async def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict:
        exercise = str(arguments.get("exercise", "")).strip()
        injury = str(arguments.get("injury_or_limit") or "").strip()
        equipment = [str(e).strip() for e in (arguments.get("equipment") or []) if str(e).strip()]

        source = await ctx.db.scalar(
            select(GraphEntity).where(GraphEntity.name.ilike(f"%{exercise}%")).limit(1)
        )
        alternatives: list[dict] = []

        if source is not None:
            edges = (
                await ctx.db.scalars(
                    select(GraphEdge).where(
                        GraphEdge.target_id == source.id,
                        GraphEdge.relation_type == "alternative_for",
                    )
                )
            ).all()
            alt_ids = [e.source_id for e in edges]
            if alt_ids:
                entities = (
                    await ctx.db.scalars(select(GraphEntity).where(GraphEntity.id.in_(alt_ids)))
                ).all()
                for ent in entities:
                    alternatives.append(
                        {
                            "name": ent.name,
                            "entity_type": ent.entity_type,
                            "reason": f"{ent.name} 可作为 {exercise} 的替代",
                        }
                    )

        if not alternatives:
            fallback_map = {
                "深蹲": ["箱式深蹲", "保加利亚分腿蹲", "臀桥"],
                "硬拉": ["罗马尼亚硬拉", "臀桥", "壶铃摇摆"],
            }
            for name in fallback_map.get(exercise, []):
                alternatives.append({"name": name, "entity_type": "exercise", "reason": "规则库推荐"})

        if injury:
            alternatives = [
                a
                for a in alternatives
                if injury not in a["name"]
            ]

        if equipment:
            alternatives = [
                a
                for a in alternatives
                if any(eq in a["name"] or eq in exercise for eq in equipment) or not equipment
            ]

        return {
            "exercise": exercise,
            "injury_or_limit": injury or None,
            "alternatives": alternatives,
            "output_preview": ", ".join(a["name"] for a in alternatives[:3]) or "暂无替代建议",
        }
