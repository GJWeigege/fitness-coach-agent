import uuid

from app.db.models import AgentStep
from app.schemas.chat import parse_message_step_items
from app.services.chat_service import collect_agent_step
from app.services.chat_session_service import agent_step_record_to_item, sanitize_step_detail


def test_collect_agent_step_from_step_event():
    step = collect_agent_step(
        {
            "type": "step",
            "phase": "planning",
            "summary": "正在制定执行计划…",
            "step_index": 1,
            "detail": {"agent": "training"},
        }
    )
    assert step == {
        "phase": "planning",
        "summary": "正在制定执行计划…",
        "step_index": 1,
        "detail": {"agent": "training"},
    }


def test_collect_agent_step_skips_incomplete_step_event():
    assert collect_agent_step({"type": "step", "phase": "planning"}) is None
    assert collect_agent_step({"type": "step", "summary": "missing phase"}) is None
    assert collect_agent_step({"type": "unknown", "phase": "x"}) is None


def test_collect_agent_step_from_tool_events():
    call = collect_agent_step(
        {
            "type": "tool_call",
            "tool": "knowledge_search",
            "arguments": {"query": "增肌"},
        }
    )
    assert call == {"phase": "tool_call", "summary": "调用 knowledge_search"}

    result = collect_agent_step({"type": "tool_result", "output_preview": "找到 3 条"})
    assert result == {"phase": "tool_result", "summary": "找到 3 条"}


def test_parse_message_step_items_skips_malformed_rows():
    items = parse_message_step_items(
        [
            {"phase": "routing", "summary": "ok"},
            {"phase": "broken"},
            "not-a-dict",
            {"summary": "missing phase"},
        ]
    )
    assert len(items) == 1
    assert items[0].phase == "routing"


def test_sanitize_step_detail_removes_cot():
    assert sanitize_step_detail({"plan": {"tasks": []}, "cot": "internal reasoning"}) == {
        "plan": {"tasks": []}
    }


def test_agent_step_record_to_item_redacts_cot():
    step = AgentStep(
        run_id=uuid.uuid4(),
        step_index=0,
        phase="planning",
        summary="execution plan",
        payload={"plan": {"tasks": []}, "cot": "hidden"},
    )
    item = agent_step_record_to_item(step)
    assert "cot" not in (item.get("detail") or {})
