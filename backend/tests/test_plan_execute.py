import pytest

from app.agent.coach.plan_schema import (
    ExecutionPlan,
    fallback_execution_plan,
    load_planner_prompt,
    parse_and_validate_plan,
    validate_execution_plan,
)


def test_planner_prompt_loads():
    prompt = load_planner_prompt()
    assert "tasks" in prompt
    assert "parallel_group" in prompt


def test_parse_valid_recovery_plan():
    raw = {
        "tasks": [
            {"agent": "training", "goal": "低冲击恢复训练", "parallel_group": 0},
            {"agent": "nutrition", "goal": "抗炎饮食", "parallel_group": 0},
        ],
        "constraints": ["避免深蹲"],
        "estimated_tools": ["knowledge_search", "check_contraindication"],
    }
    plan, err = validate_execution_plan(raw, ["training", "nutrition"])
    assert err is None
    assert plan is not None
    assert len(plan.tasks) == 2
    assert plan.tasks[0].agent == "training"
    assert plan.tasks[1].parallel_group == 0


def test_reject_agent_outside_active_agents():
    raw = {
        "tasks": [{"agent": "safety", "goal": "检查禁忌"}],
        "constraints": [],
        "estimated_tools": [],
    }
    plan, err = validate_execution_plan(raw, ["training"])
    assert plan is None
    assert "active_agents" in (err or "")


def test_invalid_json_triggers_fallback():
    plan, degraded, reason = parse_and_validate_plan(
        "not json",
        intent="training",
        active_agents=["training"],
        user_message="深蹲计划",
    )
    assert degraded is True
    assert reason == "invalid json"
    assert len(plan.tasks) == 1
    assert plan.tasks[0].agent == "training"


def test_invalid_agent_in_plan_triggers_fallback():
    raw = {
        "tasks": [{"agent": "nutrition", "goal": "饮食"}],
        "constraints": [],
        "estimated_tools": ["knowledge_search"],
    }
    plan, degraded, reason = parse_and_validate_plan(
        raw,
        intent="training",
        active_agents=["training"],
        user_message="训练",
    )
    assert degraded is True
    assert "active_agents" in (reason or "")
    assert plan.tasks[0].agent == "training"


def test_chitchat_empty_plan():
    plan, degraded, reason = parse_and_validate_plan(
        None,
        intent="chitchat",
        active_agents=[],
    )
    assert degraded is False
    assert reason is None
    assert plan.tasks == []


def test_fallback_recovery_two_tasks():
    plan = fallback_execution_plan(
        "recovery",
        ["training", "nutrition"],
        "恢复期安排",
    )
    assert len(plan.tasks) == 2
    assert {t.agent for t in plan.tasks} == {"training", "nutrition"}
    assert plan.tasks[0].parallel_group == 0
    assert plan.tasks[1].parallel_group == 0


def test_unknown_tool_rejected():
    raw = {
        "tasks": [{"agent": "training", "goal": "练腿"}],
        "constraints": [],
        "estimated_tools": ["order_lookup"],
    }
    plan, err = validate_execution_plan(raw, ["training"])
    assert plan is None
    assert "unknown tools" in (err or "")


def test_execution_plan_model_dump():
    plan = ExecutionPlan(
        tasks=[{"agent": "safety", "goal": "评估风险"}],
        constraints=["引用知识库"],
        estimated_tools=["check_contraindication"],
    )
    data = plan.model_dump()
    assert data["tasks"][0]["agent"] == "safety"
