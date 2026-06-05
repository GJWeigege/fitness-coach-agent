from langchain_core.runnables import RunnableConfig

from app.agent.coach.state import CoachState
from app.agent.guardrails import COACH_DISCLAIMER
from app.agent.intent_router import SAFETY_KEYWORDS

RED_FLAG_KEYWORDS = SAFETY_KEYWORDS + (
    "昏厥",
    "咳血",
    "剧烈头痛",
    "无法呼吸",
    "自杀",
)


def _contains_red_flag(text: str) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in RED_FLAG_KEYWORDS)


async def safety_review_node(state: CoachState, config: RunnableConfig) -> dict:
    del config
    combined = state.get("user_message", "")
    for output in (state.get("agent_outputs") or {}).values():
        combined += "\n" + output

    blocked = _contains_red_flag(combined)
    if state.get("intent") == "safety" and _contains_red_flag(state.get("user_message", "")):
        blocked = True

    return {"safety_blocked": blocked}


SAFETY_BLOCKED_TEMPLATE = (
    "您的描述涉及可能需要专业医疗评估的情况。"
    "在获得医生或康复治疗师明确许可前，请避免自行进行高强度或复杂训练，并尽快就医评估。\n\n"
    f"{COACH_DISCLAIMER}"
)
