from langchain_core.runnables import RunnableConfig

from app.agent.coach.state import CoachState
from app.agent.intent_router import CoachIntentRouter


async def route_intent_node(state: CoachState, config: RunnableConfig) -> dict:
    conf = config.get("configurable") or {}
    llm = conf["llm"]
    router = conf.get("intent_router") or CoachIntentRouter(llm)
    result = await router.route(state.get("user_message", ""), use_rag=state.get("use_rag", True))
    return {
        "intent": result["intent"],
        "active_agents": result["active_agents"],
    }
