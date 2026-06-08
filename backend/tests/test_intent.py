import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.intent_router import (
    INTENT_ACTIVE_AGENTS,
    CoachIntentRouter,
    VALID_INTENTS,
    has_injury_indicator,
    load_router_prompt,
)
from app.llm.dashscope_client import ChatResult


class MockLLM:
    def __init__(self, response: dict | None = None) -> None:
        self.response = response
        self.settings = MagicMock(coach_router_model="qwen-plus")

    async def chat(self, messages, *, model=None):
        del messages, model
        if self.response is None:
            raise RuntimeError("LLM unavailable")
        content = json.dumps(self.response, ensure_ascii=False)
        return ChatResult(content=content, model_name="qwen-plus", prompt_tokens=1, completion_tokens=1, total_tokens=2)


@pytest.fixture
def router():
    return CoachIntentRouter(MockLLM())


def test_valid_intents_set():
    assert VALID_INTENTS == {
        "training",
        "nutrition",
        "recovery",
        "safety",
        "profile",
        "chitchat",
        "unknown",
    }


def test_router_prompt_loads():
    prompt = load_router_prompt()
    assert "training" in prompt
    assert "recovery" in prompt


@pytest.mark.asyncio
async def test_chitchat_greeting(router):
    result = await router.route("你好")
    assert result["intent"] == "chitchat"
    assert result["active_agents"] == []


@pytest.mark.asyncio
async def test_training_keyword(router):
    result = await router.route("帮我安排一下深蹲训练计划")
    assert result["intent"] == "training"
    assert result["active_agents"] == ["training"]


@pytest.mark.asyncio
async def test_nutrition_keyword(router):
    result = await router.route("增肌期蛋白质应该怎么吃")
    assert result["intent"] == "nutrition"
    assert result["active_agents"] == ["nutrition"]


@pytest.mark.asyncio
async def test_recovery_keyword_dual_agents(router):
    result = await router.route("帮我制定恢复期的训练和饮食计划")
    assert result["intent"] == "recovery"
    assert result["active_agents"] == INTENT_ACTIVE_AGENTS["recovery"]


@pytest.mark.asyncio
async def test_safety_keyword(router):
    result = await router.route("我膝盖受伤还能深蹲吗")
    assert result["intent"] == "safety"
    assert result["active_agents"] == ["safety"]


@pytest.mark.asyncio
async def test_safety_eval_001_knee_injury_past_tense(router):
    result = await router.route("我膝盖受过伤，还能深蹲吗？")
    assert result["intent"] == "safety"
    assert result["active_agents"] == ["safety"]


@pytest.mark.asyncio
async def test_safety_eval_008_pain_during_lift(router):
    result = await router.route("硬拉时腰有点疼，是不是动作错了？")
    assert result["intent"] == "safety"
    assert result["active_agents"] == ["safety"]


@pytest.mark.asyncio
async def test_pain_compound_words_do_not_trigger_safety(router):
    assert has_injury_indicator("今天训练很痛快") is False
    assert has_injury_indicator("我不痛") is False
    result = await router.route("今天训练很痛快")
    assert result["intent"] == "training"
    result = await router.route("我不痛，可以继续练")
    assert result["intent"] != "safety"


@pytest.mark.asyncio
async def test_affection_word_does_not_trigger_safety(router):
    assert has_injury_indicator("疼爱") is False
    result = await router.route("这份疼爱很温暖")
    assert result["intent"] != "safety"


@pytest.mark.asyncio
async def test_profile_keyword(router):
    result = await router.route("更新一下我的健身档案")
    assert result["intent"] == "profile"
    assert result["active_agents"] == ["profile"]


@pytest.mark.asyncio
async def test_use_rag_false_short_chitchat():
    router = CoachIntentRouter(MockLLM())
    result = await router.route("随便聊聊", use_rag=False)
    assert result["intent"] == "chitchat"


@pytest.mark.asyncio
async def test_llm_parse_training():
    router = CoachIntentRouter(
        MockLLM({"intent": "training", "confidence": 0.92, "reason": "LLM"})
    )
    result = await router.route("如何系统化提高1RM")
    assert result["intent"] == "training"
    assert result["confidence"] == 0.92


@pytest.mark.asyncio
async def test_llm_invalid_intent_falls_back_unknown():
    router = CoachIntentRouter(
        MockLLM({"intent": "order", "confidence": 0.9, "reason": "bad"})
    )
    result = await router.route("something odd")
    assert result["intent"] == "unknown"


@pytest.mark.asyncio
async def test_llm_failure_unknown():
    router = CoachIntentRouter(MockLLM())
    result = await router.route("xyz ambiguous question without keywords")
    assert result["intent"] == "unknown"
    assert result["active_agents"] == []


@pytest.mark.asyncio
async def test_recovery_llm_response():
    router = CoachIntentRouter(
        MockLLM({"intent": "recovery", "confidence": 0.88, "reason": "综合恢复"})
    )
    result = await router.route("deload 周怎么安排")
    assert result["intent"] == "recovery"
    assert result["active_agents"] == ["training", "nutrition"]
