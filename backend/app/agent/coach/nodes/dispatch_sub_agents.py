from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from app.agent.coach.plan_schema import PlanTask
from app.agent.coach.state import CoachState
from app.core.config import get_settings


def _tasks_from_state(state: CoachState) -> list[PlanTask]:
    plan = state.get("execution_plan") or {}
    raw_tasks = plan.get("tasks") or []
    tasks: list[PlanTask] = []
    for item in raw_tasks:
        if isinstance(item, PlanTask):
            tasks.append(item)
        else:
            tasks.append(PlanTask.model_validate(item))
    return tasks


def _sub_agent_send_payload(state: CoachState, task: PlanTask) -> dict:
    return {
        **state,
        "current_agent_key": task.agent,
        "task_goal": task.goal,
    }


def _mark_parallel_used(config: RunnableConfig, used: bool) -> None:
    conf = config.get("configurable") or {}
    run_meta = conf.get("run_meta")
    if isinstance(run_meta, dict):
        run_meta["parallel_agents_used"] = used


def route_after_plan_execute(state: CoachState, config: RunnableConfig):
    intent = state.get("intent", "unknown")
    if intent == "chitchat":
        return "coach_chitchat"
    if intent == "unknown":
        return "knowledge_prefetch"

    settings = get_settings()
    tasks = _tasks_from_state(state)
    if not tasks:
        active = state.get("active_agents") or []
        if active:
            tasks = [
                PlanTask(agent=agent, goal=state.get("user_message", "")[:120] or "回应用户诉求")
                for agent in active[: settings.max_sub_agents_per_turn]
            ]
        else:
            return "coach_chitchat"

    tasks = tasks[: settings.max_sub_agents_per_turn]

    if not settings.parallel_sub_agents_enabled and len(tasks) > 1:
        _mark_parallel_used(config, False)
        return "serial_dispatch"

    if len(tasks) == 1:
        _mark_parallel_used(config, False)
        return Send("sub_agent", _sub_agent_send_payload(state, tasks[0]))

    parallel_groups = {t.parallel_group for t in tasks if t.parallel_group is not None}
    if len(tasks) > 1 and len(parallel_groups) <= 1:
        _mark_parallel_used(config, True)
        return [Send("sub_agent", _sub_agent_send_payload(state, task)) for task in tasks]

    _mark_parallel_used(config, False)
    return Send("sub_agent", _sub_agent_send_payload(state, tasks[0]))


async def serial_dispatch_node(state: CoachState, config: RunnableConfig) -> dict:
    from app.agent.coach.nodes.sub_agent import sub_agent_node

    settings = get_settings()
    tasks = _tasks_from_state(state)
    if not tasks:
        active = state.get("active_agents") or []
        tasks = [
            PlanTask(agent=agent, goal=state.get("user_message", "")[:120] or "回应用户诉求")
            for agent in active[: settings.max_sub_agents_per_turn]
        ]

    merged_outputs: dict[str, str] = {}
    merged_tools: list[dict] = []
    merged_cot: dict[str, str] = {}
    status = state.get("status", "completed")

    current = dict(state)
    for task in tasks[: settings.max_sub_agents_per_turn]:
        current["current_agent_key"] = task.agent
        current["task_goal"] = task.goal
        result = await sub_agent_node(current, config)
        merged_outputs.update(result.get("agent_outputs") or {})
        merged_tools.extend(result.get("tool_calls") or [])
        merged_cot.update(result.get("cot_traces") or {})
        if result.get("status") == "degraded":
            status = "degraded"
        current = {**current, **result}

    updates: dict = {
        "agent_outputs": merged_outputs,
        "tool_calls": merged_tools,
    }
    if merged_cot:
        updates["cot_traces"] = merged_cot
    if status == "degraded":
        updates["status"] = status
    return updates
