from langchain_core.runnables import RunnableConfig

from app.agent.coach.nodes.build_llm_messages import build_llm_messages
from app.agent.coach.nodes.safety_review import SAFETY_BLOCKED_TEMPLATE
from app.agent.coach.state import CoachState
from app.core.config import get_settings
from app.llm.dashscope_client import StreamDone


def _passthrough_answer(state: CoachState) -> str:
    outputs = state.get("agent_outputs") or {}
    if not outputs:
        return ""
    if "chitchat" in outputs:
        return outputs["chitchat"]
    if len(outputs) == 1:
        return next(iter(outputs.values()))
    active = state.get("active_agents") or []
    for key in active:
        if key in outputs:
            return outputs[key]
    return next(iter(outputs.values()))


def _should_merge_with_llm(state: CoachState) -> bool:
    active_agents = state.get("active_agents") or []
    outputs = state.get("agent_outputs") or {}
    if len(active_agents) >= 2 and len(outputs) >= 2:
        return True
    plan = state.get("execution_plan") or {}
    tasks = plan.get("tasks") or []
    return len(tasks) >= 2 and len(outputs) >= 2


async def synthesize_node(state: CoachState, config: RunnableConfig) -> dict:
    conf = config.get("configurable") or {}
    emit = conf.get("emit")
    settings = get_settings()

    if state.get("safety_blocked"):
        final_answer = SAFETY_BLOCKED_TEMPLATE
        if emit:
            await emit("replace", {"content": final_answer})
        return {"final_answer": final_answer}

    intent = state.get("intent", "unknown")
    if intent in {"chitchat", "unknown"} or not _should_merge_with_llm(state):
        answer = _passthrough_answer(state)
        if emit:
            await emit("replace", {"content": answer})
        return {"final_answer": answer}

    llm = conf["llm"]
    messages, _ = await build_llm_messages(state, config, agent_key="synthesize")
    constraints = (state.get("execution_plan") or {}).get("constraints") or []
    agent_outputs = state.get("agent_outputs") or {}
    merge_context = (
        "请将以下各子 agent 输出合并为一段连贯、可执行的中文建议，并遵守约束：\n"
        f"约束：{'; '.join(constraints) if constraints else '无'}\n\n"
    )
    for key, text in agent_outputs.items():
        merge_context += f"【{key}】\n{text}\n\n"
    messages.append({"role": "user", "content": merge_context})

    text = ""
    async for chunk in llm.chat_stream(messages, model=settings.coach_answer_model):
        if isinstance(chunk, str):
            text += chunk
            if emit:
                await emit("delta", {"content": chunk})
        elif isinstance(chunk, StreamDone):
            break

    return {"final_answer": text}
