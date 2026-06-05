import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

VALID_PLAN_AGENTS = frozenset({"training", "nutrition", "safety", "profile"})
VALID_ESTIMATED_TOOLS = frozenset(
    {
        "knowledge_search",
        "check_contraindication",
        "get_user_profile",
        "log_training",
        "calculate_macros",
        "suggest_alternatives",
        "graph_lookup",
    }
)

_PLANNER_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "coach" / "planner.txt"


def load_planner_prompt() -> str:
    return _PLANNER_PROMPT_PATH.read_text(encoding="utf-8")


class PlanTask(BaseModel):
    agent: str
    goal: str
    parallel_group: int | None = None

    @field_validator("agent")
    @classmethod
    def agent_must_be_valid(cls, value: str) -> str:
        if value not in VALID_PLAN_AGENTS:
            raise ValueError(f"invalid agent: {value}")
        return value


class ExecutionPlan(BaseModel):
    tasks: list[PlanTask] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    estimated_tools: list[str] = Field(default_factory=list)

    @field_validator("estimated_tools")
    @classmethod
    def tools_must_be_known(cls, value: list[str]) -> list[str]:
        unknown = [t for t in value if t not in VALID_ESTIMATED_TOOLS]
        if unknown:
            raise ValueError(f"unknown tools: {unknown}")
        return value


def parse_plan_json(raw: str | dict) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return None
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


def validate_execution_plan(
    plan_data: dict,
    active_agents: list[str],
) -> tuple[ExecutionPlan | None, str | None]:
    try:
        plan = ExecutionPlan.model_validate(plan_data)
    except Exception as exc:
        return None, str(exc)

    allowed = set(active_agents)
    invalid = [t.agent for t in plan.tasks if t.agent not in allowed]
    if invalid:
        return None, f"tasks agent not in active_agents: {invalid}"
    return plan, None


def fallback_execution_plan(
    intent: str,
    active_agents: list[str],
    user_message: str,
) -> ExecutionPlan:
    if intent == "chitchat" or not active_agents:
        return ExecutionPlan(tasks=[], constraints=[], estimated_tools=[])

    goal_prefix = user_message.strip()[:120] or "回应用户诉求"
    tasks: list[PlanTask] = []
    parallel_group = 0 if intent == "recovery" and len(active_agents) >= 2 else None
    for agent in active_agents:
        tasks.append(
            PlanTask(
                agent=agent,
                goal=f"针对「{goal_prefix}」给出{agent}建议",
                parallel_group=parallel_group if parallel_group is not None else None,
            )
        )
    return ExecutionPlan(
        tasks=tasks,
        constraints=["引用知识库", "避免诊断性表述"],
        estimated_tools=["knowledge_search"],
    )


def parse_and_validate_plan(
    raw: str | dict | None,
    *,
    intent: str,
    active_agents: list[str],
    user_message: str = "",
) -> tuple[ExecutionPlan, bool, str | None]:
    """Return (plan, degraded, error_reason)."""
    if intent == "chitchat":
        return ExecutionPlan(tasks=[], constraints=[], estimated_tools=[]), False, None

    if raw is None:
        return fallback_execution_plan(intent, active_agents, user_message), True, "empty plan"

    data = parse_plan_json(raw) if isinstance(raw, str) else raw
    if not data:
        return fallback_execution_plan(intent, active_agents, user_message), True, "invalid json"

    plan, err = validate_execution_plan(data, active_agents)
    if plan is None:
        return fallback_execution_plan(intent, active_agents, user_message), True, err
    return plan, False, None
