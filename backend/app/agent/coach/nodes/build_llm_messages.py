import uuid

from langchain_core.runnables import RunnableConfig

from app.agent.coach.graph_context import format_graph_context_block
from app.agent.coach.state import CoachState
from app.agent.guardrails import COACH_DISCLAIMER
from app.prompts.coach_system_prompt import COACH_SYSTEM_PROMPT
from app.services.memory_service import MemoryBuildResult, MemoryService

AGENT_ROLE_SUFFIX: dict[str, str] = {
    "training": "\n\n【本轮角色】训练教练：聚焦动作选择、训练量与周期化建议。",
    "nutrition": "\n\n【本轮角色】营养教练：聚焦宏量、餐次与恢复饮食建议。",
    "safety": "\n\n【本轮角色】安全教练：聚焦禁忌、红旗症状与就医指引。",
    "profile": "\n\n【本轮角色】档案教练：聚焦用户画像解读与目标对齐。",
    "chitchat": "\n\n【本轮角色】通用教练：简短友好回应，避免过度展开训练计划。",
    "synthesize": "\n\n【本轮角色】综合教练：合并多 agent 输出，保持约束一致、结构清晰。",
}


def _format_profile_block(user_profile: dict | None) -> str:
    if not user_profile:
        return ""
    parts: list[str] = []
    for key in ("goals", "experience_level", "injuries", "equipment", "diet_preference"):
        value = user_profile.get(key)
        if value:
            parts.append(f"{key}: {value}")
    for key in ("age", "sex", "height_cm", "weight_kg"):
        value = user_profile.get(key)
        if value is not None:
            parts.append(f"{key}: {value}")
    if not parts:
        return ""
    return "\n\n【用户画像】\n" + "\n".join(parts)


def _agent_system_suffix(agent_key: str | None) -> str:
    if not agent_key:
        return ""
    return AGENT_ROLE_SUFFIX.get(agent_key, "")


async def build_llm_messages(
    state: CoachState,
    config: RunnableConfig,
    *,
    agent_key: str | None = None,
    include_cot: bool = False,
) -> tuple[list[dict], MemoryBuildResult]:
    conf = config.get("configurable") or {}
    db = conf["db"]
    memory_svc = conf.get("memory_service") or MemoryService()

    context_block = (
        _format_profile_block(state.get("user_profile"))
        + format_graph_context_block(state.get("graph_context"))
        + _agent_system_suffix(agent_key)
        + f"\n\n{COACH_DISCLAIMER}"
    )

    if include_cot:
        from app.agent.coach.cot import load_cot_instruction

        context_block += "\n\n" + load_cot_instruction()

    memory_result = await memory_svc.build_context_messages(
        db,
        uuid.UUID(state["session_id"]),
        context_block=context_block,
        system_prompt=COACH_SYSTEM_PROMPT,
        exclude_message_id=uuid.UUID(state["user_message_id"])
        if state.get("user_message_id")
        else None,
    )

    run_meta = conf.get("run_meta")
    if isinstance(run_meta, dict):
        if memory_result.memory_compacted:
            run_meta["memory_compacted"] = True
        run_meta["dropped_message_count"] = max(
            int(run_meta.get("dropped_message_count") or 0),
            memory_result.dropped_message_count,
        )

    messages = list(memory_result.messages)
    user_message = state.get("user_message", "")
    if user_message:
        already_present = any(
            msg.get("role") == "user" and msg.get("content") == user_message for msg in messages
        )
        if not already_present:
            messages.append({"role": "user", "content": user_message})

    task_goal = state.get("task_goal")
    if task_goal and agent_key in {"training", "nutrition", "safety", "profile"}:
        messages.append({"role": "system", "content": f"【本轮子目标】{task_goal}"})

    return messages, memory_result
