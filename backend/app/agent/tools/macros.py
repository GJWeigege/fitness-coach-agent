from typing import Any

from app.agent.tools.base import ToolContext
from app.services.profile_service import ProfileService


class CalculateMacrosTool:
    name = "calculate_macros"
    description = "根据用户画像估算每日热量与宏量营养素（蛋白质/碳水/脂肪）。"

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
                        "activity_factor": {
                            "type": "number",
                            "description": "活动系数 1.2-1.9，默认 1.55",
                        },
                    },
                    "required": [],
                },
            },
        }

    async def run(self, ctx: ToolContext, arguments: dict[str, Any]) -> dict:
        profile = await self.profile_service.get_profile(ctx.db, ctx.user_id)
        activity_factor = float(arguments.get("activity_factor") or 1.55)

        weight = profile.weight_kg or 70.0
        height = profile.height_cm or 170.0
        age = profile.age or 30
        sex = (profile.sex or "male").lower()

        if sex in {"female", "f", "女"}:
            bmr = 10 * weight + 6.25 * height - 5 * age - 161
        else:
            bmr = 10 * weight + 6.25 * height - 5 * age + 5

        tdee = round(bmr * activity_factor)
        protein_g = round(weight * 1.8)
        fat_g = round(weight * 0.8)
        protein_kcal = protein_g * 4
        fat_kcal = fat_g * 9
        carb_kcal = max(tdee - protein_kcal - fat_kcal, 0)
        carb_g = round(carb_kcal / 4)

        goals = profile.goals or []
        note = "维持热量"
        if any("减脂" in g or "减重" in g for g in goals):
            tdee = round(tdee * 0.85)
            note = "轻度热量缺口（约 15%）"
            carb_kcal = max(tdee - protein_kcal - fat_kcal, 0)
            carb_g = round(carb_kcal / 4)
        elif any("增肌" in g for g in goals):
            tdee = round(tdee * 1.1)
            note = "轻度热量盈余（约 10%）"
            carb_kcal = max(tdee - protein_kcal - fat_kcal, 0)
            carb_g = round(carb_kcal / 4)

        return {
            "bmr_kcal": round(bmr),
            "tdee_kcal": tdee,
            "protein_g": protein_g,
            "carb_g": carb_g,
            "fat_g": fat_g,
            "note": note,
            "based_on_profile": profile.model_dump(mode="json"),
        }
