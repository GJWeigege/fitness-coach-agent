from langchain_core.runnables import RunnableConfig

from app.agent.coach.cot import split_cot
from app.agent.coach.nodes.build_llm_messages import build_llm_messages
from app.agent.coach.state import CoachState
from app.core.config import get_settings
from app.llm.dashscope_client import StreamDone


async def coach_chitchat_node(state: CoachState, config: RunnableConfig) -> dict:
    conf = config.get("configurable") or {}
    settings = get_settings()
    llm = conf["llm"]

    messages, _ = await build_llm_messages(
        state,
        config,
        agent_key="chitchat",
        include_cot=settings.cot_enabled,
    )

    accumulated = ""
    async for chunk in llm.chat_stream(messages):
        if isinstance(chunk, str):
            accumulated += chunk
        elif isinstance(chunk, StreamDone):
            break

    reasoning, answer = split_cot(accumulated)
    updates: dict = {"agent_outputs": {"chitchat": answer or accumulated.strip()}}
    if reasoning:
        updates["cot_traces"] = {"chitchat": reasoning}
    return updates
