import json
import time
import uuid

from langchain_core.runnables import RunnableConfig

from app.agent.coach.plan_schema import ExecutionPlan, load_planner_prompt, parse_and_validate_plan
from app.agent.coach.cot import load_cot_instruction, split_cot
from app.agent.coach.state import CoachState
from app.agent.coach.token_usage import track_llm_usage
from app.core.config import get_settings


async def plan_execute_node(state: CoachState, config: RunnableConfig) -> dict:
    intent = state.get("intent", "unknown")
    active_agents = state.get("active_agents") or []
    conf = config.get("configurable") or {}

    if intent == "chitchat":
        plan = ExecutionPlan(tasks=[], constraints=[], estimated_tools=[])
        return {"execution_plan": plan.model_dump()}

    settings = get_settings()
    llm = conf["llm"]
    user_profile = state.get("user_profile") or {}
    planner_input = {
        "intent": intent,
        "active_agents": active_agents,
        "user_message": state.get("user_message", ""),
        "user_profile": user_profile,
    }
    messages = [
        {"role": "system", "content": load_planner_prompt()},
        {"role": "user", "content": json.dumps(planner_input, ensure_ascii=False)},
    ]
    if settings.cot_enabled:
        messages[0]["content"] = f"{messages[0]['content']}\n\n{load_cot_instruction()}"

    start = time.perf_counter()
    result = await llm.chat(messages, model=settings.coach_planner_model)
    duration_ms = int((time.perf_counter() - start) * 1000)
    reasoning, plan_text = split_cot(result.content)
    plan, degraded, reason = parse_and_validate_plan(
        plan_text or result.content,
        intent=intent,
        active_agents=active_agents,
        user_message=state.get("user_message", ""),
    )

    updates: dict = {"execution_plan": plan.model_dump()}
    if reasoning:
        updates["cot_traces"] = {"planner": reasoning}
    if degraded:
        updates["status"] = "degraded"

    obs = conf.get("observability")
    run_id = state.get("run_id")
    planning_step_id = None
    if obs and run_id:
        step = await obs.append_step(
            conf["db"],
            uuid.UUID(run_id),
            phase="planning",
            summary="execution plan",
            payload={
                "plan": plan.model_dump(),
                "degraded": degraded,
                "reason": reason,
                "cot": reasoning,
            },
            duration_ms=duration_ms,
        )
        planning_step_id = step.id

    await track_llm_usage(
        conf,
        run_id=state["run_id"],
        purpose="planner",
        model=result.model_name or settings.coach_planner_model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=duration_ms,
        step_id=planning_step_id,
    )

    return updates
