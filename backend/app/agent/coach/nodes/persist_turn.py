from langchain_core.runnables import RunnableConfig

from app.agent.coach.state import CoachState


async def persist_turn_node(state: CoachState, config: RunnableConfig) -> dict:
    del state, config
    return {}
