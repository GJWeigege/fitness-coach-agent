from typing import Any

from sqlalchemy import select

from app.agent.tools.base import ToolContext
from app.db.models import GraphEdge, GraphEntity

# Static rules when graph has no match (exercise -> injury keywords)
STATIC_CONTRAINDICATIONS: dict[str, list[str]] = {
    "深蹲": ["膝盖损伤", "急性膝痛", "术后恢复期"],
    "硬拉": ["腰椎间盘突出", "急性腰痛", "妊娠中晚期"],
    "颈后推举": ["肩袖损伤", "肩峰撞击"],
    "跑步": ["应力性骨折", "急性踝扭伤"],
}


class CheckContraindicationTool:
    name = "check_contraindication"
    description = "检查某动作/训练对用户伤病或症状是否存在禁忌。"

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "exercise": {"type": "string", "description": "动作或训练名称"},
                        "conditions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "用户伤病、症状或限制条件",
                        },
                    },
                    "required": ["exercise", "conditions"],
                },
            },
        }

    async def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict:
        exercise = str(arguments.get("exercise", "")).strip()
        conditions = [str(c).strip() for c in (arguments.get("conditions") or []) if str(c).strip()]
        if not exercise:
            return {"contraindicated": False, "reasons": [], "matched_rules": []}

        reasons: list[str] = []
        matched: list[str] = []

        entity = await ctx.db.scalar(
            select(GraphEntity).where(GraphEntity.name.ilike(f"%{exercise}%")).limit(1)
        )
        if entity is not None:
            edges = (
                await ctx.db.scalars(
                    select(GraphEdge).where(
                        GraphEdge.source_id == entity.id,
                        GraphEdge.relation_type == "contraindicated_for",
                    )
                )
            ).all()
            target_ids = [e.target_id for e in edges]
            if target_ids:
                targets = {
                    row.id: row
                    for row in (
                        await ctx.db.scalars(
                            select(GraphEntity).where(GraphEntity.id.in_(target_ids))
                        )
                    ).all()
                }
                for edge in edges:
                    target = targets.get(edge.target_id)
                    if target is None:
                        continue
                    for cond in conditions:
                        if cond in target.name or target.name in cond:
                            reasons.append(f"{exercise} 对 {target.name} 可能存在禁忌")
                            matched.append(f"graph:{target.name}")

        static_rules = STATIC_CONTRAINDICATIONS.get(exercise, [])
        for rule in static_rules:
            for cond in conditions:
                if rule in cond or cond in rule:
                    msg = f"{exercise} 在 {rule} 情况下需谨慎或避免"
                    if msg not in reasons:
                        reasons.append(msg)
                        matched.append(f"static:{rule}")

        return {
            "contraindicated": bool(reasons),
            "reasons": reasons,
            "matched_rules": matched,
            "exercise": exercise,
            "conditions": conditions,
        }
