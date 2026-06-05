import uuid

from langchain_core.runnables import RunnableConfig

from app.agent.coach.state import CoachState
from app.services.profile_service import ProfileService


async def load_profile_node(state: CoachState, config: RunnableConfig) -> dict:
    conf = config.get("configurable") or {}
    db = conf["db"]
    profile_svc = conf.get("profile_service") or ProfileService()
    user_id = uuid.UUID(state["user_id"])
    profile = await profile_svc.get_profile(db, user_id)
    return {"user_profile": profile.model_dump(mode="json")}
