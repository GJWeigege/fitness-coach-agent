import json
import logging
import time
import uuid

from langchain_core.runnables import RunnableConfig

from app.agent.coach.cot import split_cot
from app.agent.coach.nodes.build_llm_messages import build_llm_messages
from app.agent.coach.state import CoachState
from app.agent.coach.token_usage import track_llm_usage
from app.agent.tools.base import ToolContext
from app.core.config import get_settings
from app.llm.dashscope_client import StreamDone, ToolCallComplete

logger = logging.getLogger(__name__)


async def sub_agent_node(state: CoachState, config: RunnableConfig) -> dict:
    agent_key = state.get("current_agent_key")
    if not agent_key:
        return {}

    conf = config.get("configurable") or {}
    settings = get_settings()
    llm = conf["llm"]
    registry = conf["tool_registry"]

    messages, _ = await build_llm_messages(
        state,
        config,
        agent_key=agent_key,
        include_cot=settings.cot_enabled,
    )
    tool_schemas = registry.list_schemas(agent_key=agent_key)

    tool_calls_out: list[dict] = []
    cot_traces: dict[str, str] = {}
    final_answer = ""
    answer_text = ""
    accumulated = ""
    degraded = False

    tool_ctx = ToolContext(
        db=conf["db"],
        user_id=uuid.UUID(state["user_id"]),
        session_id=uuid.UUID(state["session_id"]),
        message_id=uuid.UUID(state["user_message_id"]),
        run_id=uuid.UUID(state["run_id"]),
        use_rag=state.get("use_rag", True),
    )

    for _ in range(settings.sub_agent_max_tool_steps):
        accumulated = ""
        pending_tool_calls: list[ToolCallComplete] = []
        stream_done: StreamDone | None = None

        async for chunk in llm.chat_stream_with_tools(messages, tool_schemas):
            if isinstance(chunk, str):
                accumulated += chunk
            elif isinstance(chunk, ToolCallComplete):
                pending_tool_calls.append(chunk)
            elif isinstance(chunk, StreamDone):
                stream_done = chunk
                break

        if stream_done is not None:
            await track_llm_usage(
                conf,
                run_id=state["run_id"],
                purpose=f"sub_agent:{agent_key}",
                model=stream_done.model_name or settings.coach_answer_model,
                prompt_tokens=stream_done.prompt_tokens,
                completion_tokens=stream_done.completion_tokens,
            )
        elif accumulated:
            logger.warning(
                "sub_agent_stream_missing_usage run_id=%s agent=%s",
                state.get("run_id"),
                agent_key,
            )

        reasoning, answer_text = split_cot(accumulated)
        emit = conf.get("emit")
        sse_enabled = settings.agent_enable_thinking_steps
        if reasoning:
            cot_traces[agent_key] = reasoning
            if emit and sse_enabled and settings.cot_sse_enabled:
                preview = reasoning if len(reasoning) <= 240 else f"{reasoning[:240]}…"
                await emit(
                    "step",
                    {
                        "phase": "reasoning",
                        "agent": agent_key,
                        "summary": preview,
                    },
                )

        if pending_tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": accumulated or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in pending_tool_calls
                    ],
                }
            )
            for tc in pending_tool_calls:
                if emit and sse_enabled:
                    await emit(
                        "tool_call",
                        {
                            "tool": tc.name,
                            "arguments": tc.arguments,
                            "agent": agent_key,
                        },
                    )
                start = time.perf_counter()
                try:
                    result = await registry.execute(tc.name, tool_ctx, tc.arguments)
                    status = "ok"
                except Exception as exc:
                    result = {"error": str(exc)}
                    status = "error"
                duration_ms = int((time.perf_counter() - start) * 1000)
                tool_calls_out.append(
                    {
                        "agent": agent_key,
                        "name": tc.name,
                        "arguments": tc.arguments,
                        "result": result,
                        "status": status,
                        "duration_ms": duration_ms,
                    }
                )
                if emit and sse_enabled:
                    preview = json.dumps(result, ensure_ascii=False)
                    if len(preview) > 200:
                        preview = f"{preview[:200]}…"
                    await emit(
                        "tool_result",
                        {
                            "tool": tc.name,
                            "output_preview": preview,
                            "status": status,
                            "agent": agent_key,
                        },
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
            continue

        final_answer = answer_text or accumulated.strip()
        break
    else:
        degraded = True
        final_answer = answer_text or accumulated.strip()

    updates: dict = {
        "agent_outputs": {agent_key: final_answer},
        "tool_calls": tool_calls_out,
    }
    if cot_traces:
        updates["cot_traces"] = cot_traces
    if degraded:
        updates["status"] = "degraded"
    return updates
