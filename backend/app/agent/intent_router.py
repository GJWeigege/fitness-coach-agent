import json
import logging
import re
from pathlib import Path

from app.llm.dashscope_client import DashScopeClient

logger = logging.getLogger(__name__)

VALID_INTENTS = frozenset(
    {"training", "nutrition", "recovery", "safety", "profile", "chitchat", "unknown"}
)
SUB_AGENT_KEYS = frozenset({"training", "nutrition", "safety", "profile"})

INTENT_ACTIVE_AGENTS: dict[str, list[str]] = {
    "training": ["training"],
    "nutrition": ["nutrition"],
    "recovery": ["training", "nutrition"],
    "safety": ["safety"],
    "profile": ["profile"],
    "chitchat": [],
    "unknown": [],
}

CHITCHAT_KEYWORDS = ("你好", "谢谢", "再见", "嗨", "hello", "hi", "早上好", "晚安")
SAFETY_KEYWORDS = (
    "疼痛",
    "受伤",
    "胸闷",
    "气短",
    "就医",
    "医院",
    "禁忌",
    "红旗",
    "能不能做",
    "可以做吗",
    "诊断",
    "骨折",
    "撕裂",
)
RECOVERY_KEYWORDS = ("恢复", "恢复期", "康复", "deload", "减载")
TRAINING_KEYWORDS = ("训练", "深蹲", "硬拉", "卧推", "周期", "组数", "动作", "有氧", "力量")
NUTRITION_KEYWORDS = ("营养", "蛋白质", "饮食", "热量", "宏量", "碳水", "脂肪", "补剂", "餐")
PROFILE_KEYWORDS = ("我的身高", "我的体重", "更新资料", "个人资料", "健身档案", "我的目标", "我的伤病")

_ROUTER_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "coach" / "router.txt"


def load_router_prompt() -> str:
    return _ROUTER_PROMPT_PATH.read_text(encoding="utf-8")


class CoachIntentRouter:
    def __init__(self, llm_client: DashScopeClient) -> None:
        self.llm_client = llm_client

    async def route(self, user_message: str, *, use_rag: bool = True) -> dict:
        text = user_message.strip()
        if not text:
            return self._result("unknown", 0.3, "空消息")

        lowered = text.lower()
        if len(text) <= 12 and any(k in lowered for k in CHITCHAT_KEYWORDS):
            return self._result("chitchat", 0.9, "寒暄")

        if not use_rag and any(k in text for k in TRAINING_KEYWORDS + NUTRITION_KEYWORDS):
            pass
        elif not use_rag:
            return self._result("chitchat", 0.85, "用户关闭知识库检索")

        heuristic = self._keyword_route(text)
        if heuristic:
            return heuristic

        try:
            result = await self.llm_client.chat(
                [
                    {"role": "system", "content": load_router_prompt()},
                    {"role": "user", "content": text},
                ],
                model=self.llm_client.settings.coach_router_model,
            )
            parsed = self._parse_json(result.content)
            if parsed:
                parsed["prompt_tokens"] = result.prompt_tokens
                parsed["completion_tokens"] = result.completion_tokens
                parsed["model_name"] = result.model_name
                return parsed
        except Exception as exc:
            logger.warning("coach_intent_router_llm_failed: %s", exc, exc_info=True)

        return self._result("unknown", 0.5, "默认")

    def _keyword_route(self, text: str) -> dict | None:
        if any(k in text for k in SAFETY_KEYWORDS):
            return self._result("safety", 0.85, "安全/伤病关键词")
        if any(k in text for k in RECOVERY_KEYWORDS) and (
            any(k in text for k in TRAINING_KEYWORDS) or any(k in text for k in NUTRITION_KEYWORDS)
        ):
            return self._result("recovery", 0.85, "恢复+训练/营养关键词")
        if any(k in text for k in RECOVERY_KEYWORDS):
            return self._result("recovery", 0.75, "恢复关键词")
        if any(k in text for k in PROFILE_KEYWORDS):
            return self._result("profile", 0.85, "资料关键词")
        if any(k in text for k in NUTRITION_KEYWORDS):
            return self._result("nutrition", 0.8, "营养关键词")
        if any(k in text for k in TRAINING_KEYWORDS):
            return self._result("training", 0.8, "训练关键词")
        return None

    def _result(self, intent: str, confidence: float, reason: str) -> dict:
        if intent not in VALID_INTENTS:
            intent = "unknown"
        return {
            "intent": intent,
            "confidence": confidence,
            "reason": reason,
            "active_agents": list(INTENT_ACTIVE_AGENTS[intent]),
        }

    def _parse_json(self, text: str) -> dict | None:
        if not text:
            return None
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
            intent = data.get("intent", "unknown")
            if intent not in VALID_INTENTS:
                intent = "unknown"
            return self._result(
                intent,
                float(data.get("confidence", 0.5)),
                str(data.get("reason", "")),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
