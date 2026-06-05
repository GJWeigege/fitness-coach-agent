from typing import Annotated, TypedDict


def merge_dicts(left: dict, right: dict) -> dict:
    return {**left, **right}


def merge_lists(left: list, right: list) -> list:
    return left + right


class CoachState(TypedDict, total=False):
    session_id: str
    user_id: str
    user_message_id: str
    user_message: str
    user_profile: dict | None
    intent: str
    active_agents: list[str]
    execution_plan: dict | None
    cot_traces: Annotated[dict[str, str], merge_dicts]
    rag_citations: list[dict]
    graph_context: str | None
    graph_entities_used: list[str]
    agent_outputs: Annotated[dict[str, str], merge_dicts]
    tool_calls: Annotated[list[dict], merge_lists]
    final_answer: str
    safety_blocked: bool
    run_id: str
    use_rag: bool
    status: str
    current_agent_key: str | None
    task_goal: str | None


def initial_coach_state(
    *,
    session_id: str,
    user_id: str,
    user_message_id: str,
    user_message: str,
    run_id: str,
    use_rag: bool = True,
) -> CoachState:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "user_message_id": user_message_id,
        "user_message": user_message,
        "user_profile": None,
        "intent": "unknown",
        "active_agents": [],
        "execution_plan": None,
        "cot_traces": {},
        "rag_citations": [],
        "graph_context": None,
        "graph_entities_used": [],
        "agent_outputs": {},
        "tool_calls": [],
        "final_answer": "",
        "safety_blocked": False,
        "run_id": run_id,
        "use_rag": use_rag,
        "status": "completed",
        "current_agent_key": None,
        "task_goal": None,
    }
