from langchain_core.runnables import RunnableConfig

import logging

from app.agent.coach.cot import split_cot
from app.agent.coach.nodes.build_llm_messages import build_llm_messages
from app.agent.coach.state import CoachState
from app.agent.coach.token_usage import track_llm_usage
from app.core.config import get_settings
from app.llm.dashscope_client import StreamDone

logger = logging.getLogger(__name__)


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
    stream_done: StreamDone | None = None
    async for chunk in llm.chat_stream(messages):
        if isinstance(chunk, str):
            accumulated += chunk
        elif isinstance(chunk, StreamDone):
            stream_done = chunk
            break

    if stream_done is not None:
        await track_llm_usage(
            conf,
            run_id=state["run_id"],
            purpose="chitchat",
            model=stream_done.model_name or settings.coach_answer_model,
            prompt_tokens=stream_done.prompt_tokens,
            completion_tokens=stream_done.completion_tokens,
        )
    elif accumulated:
        logger.warning(
            "chitchat_stream_missing_usage run_id=%s",
            state.get("run_id"),
        )

    reasoning, answer = split_cot(accumulated)
    updates: dict = {"agent_outputs": {"chitchat": answer or accumulated.strip()}}
    if reasoning:
        updates["cot_traces"] = {"chitchat": reasoning}
    return updates
