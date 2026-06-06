import json

from langchain_core.runnables import RunnableConfig

from app.agent.coach.state import CoachState
from app.agent.coach.token_usage import track_llm_usage
from app.agent.guardrails import COACH_DISCLAIMER
from app.agent.intent_router import SAFETY_KEYWORDS
from app.core.config import get_settings

RED_FLAG_KEYWORDS = SAFETY_KEYWORDS + (
    "昏厥",
    "咳血",
    "剧烈头痛",
    "无法呼吸",
    "自杀",
)

_SAFETY_LLM_PROMPT = (
    "你是健身客服安全审查助手。仅当用户**正在描述**需要立即就医或必须停止训练的红旗症状"
    "（如胸痛、昏厥、咳血、自杀意念、急性严重损伤、持续剧痛等）时，才应拦截。"
    "以下情况**不要**拦截：一般性恢复/训练/饮食计划咨询；知识库或教练回复中的常规安全提示、"
    "禁忌动作科普、免责声明用语。"
    "仅返回 JSON：{\"blocked\": true} 或 {\"blocked\": false}，不要其他文字。"
)


def _contains_red_flag(text: str) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in RED_FLAG_KEYWORDS)


def _parse_blocked_response(content: str) -> bool | None:
    text = (content or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and "blocked" in payload:
            return bool(payload["blocked"])
    except json.JSONDecodeError:
        pass
    lowered = text.lower()
    if "true" in lowered and "blocked" in lowered:
        return True
    if "false" in lowered and "blocked" in lowered:
        return False
    return None


async def _llm_safety_blocked(llm, review_text: str) -> tuple[bool, int | None, int | None, str | None]:
    settings = get_settings()
    messages = [
        {"role": "system", "content": _SAFETY_LLM_PROMPT},
        {"role": "user", "content": review_text[:4000]},
    ]
    try:
        result = await llm.chat(messages, model=settings.coach_router_model)
        parsed = _parse_blocked_response(result.content)
        return parsed is True, result.prompt_tokens, result.completion_tokens, result.model_name
    except Exception:
        return False, None, None, None


async def safety_review_node(state: CoachState, config: RunnableConfig) -> dict:
    user_message = state.get("user_message", "")
    intent = state.get("intent", "unknown")

    # 红旗词只审查用户原话，避免知识库/子 agent 输出中的「禁忌」「就医」等科普用语误拦。
    blocked = _contains_red_flag(user_message)

    if not blocked and intent == "safety":
        conf = config.get("configurable") or {}
        llm = conf.get("llm")
        if llm is not None:
            blocked, prompt_tokens, completion_tokens, model_name = await _llm_safety_blocked(
                llm, user_message
            )
            if prompt_tokens is not None or completion_tokens is not None:
                settings = get_settings()
                await track_llm_usage(
                    conf,
                    run_id=state["run_id"],
                    purpose="safety_review",
                    model=model_name or settings.coach_router_model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )

    return {"safety_blocked": blocked}


SAFETY_BLOCKED_TEMPLATE = (
    "您的描述涉及可能需要专业医疗评估的情况。"
    "在获得医生或康复治疗师明确许可前，请避免自行进行高强度或复杂训练，并尽快就医评估。\n\n"
    f"{COACH_DISCLAIMER}"
)
