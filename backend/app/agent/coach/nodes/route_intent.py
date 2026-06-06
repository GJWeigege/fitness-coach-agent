from langchain_core.runnables import RunnableConfig

from app.agent.coach.state import CoachState
from app.agent.coach.token_usage import track_llm_usage
from app.agent.intent_router import CoachIntentRouter


async def route_intent_node(state: CoachState, config: RunnableConfig) -> dict:
    conf = config.get("configurable") or {}
    llm = conf["llm"]
    router = conf.get("intent_router") or CoachIntentRouter(llm)
    result = await router.route(state.get("user_message", ""), use_rag=state.get("use_rag", True))

    if result.get("prompt_tokens") is not None or result.get("completion_tokens") is not None:
        await track_llm_usage(
            conf,
            run_id=state["run_id"],
            purpose="router",
            model=result.get("model_name") or llm.settings.coach_router_model,
            prompt_tokens=result.get("prompt_tokens"),
            completion_tokens=result.get("completion_tokens"),
        )

    return {
        "intent": result["intent"],
        "active_agents": result["active_agents"],
    }
