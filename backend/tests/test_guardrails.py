from app.agent.guardrails import (
    COACH_DISCLAIMER,
    FALLBACK_NO_KNOWLEDGE,
    CoachGuardrails,
    load_banned_diagnosis_terms,
)


def test_banned_terms_load():
    terms = load_banned_diagnosis_terms()
    assert "确诊" in terms
    assert len(terms) >= 5


def test_citation_guard_no_citations_searched():
    g = CoachGuardrails()
    out = g.apply_citation_guard("training", [], "编造内容", knowledge_searched=True)
    assert out == FALLBACK_NO_KNOWLEDGE


def test_citation_guard_not_searched_unchanged():
    g = CoachGuardrails()
    text = "请先补充您的训练经验。"
    assert g.apply_citation_guard("training", [], text, knowledge_searched=False) == text


def test_citation_guard_high_score():
    g = CoachGuardrails()
    citations = [{"score": 0.72, "content": "深蹲要点"}]
    text = "根据知识库，注意膝轨对齐。"
    assert g.apply_citation_guard("training", citations, text, knowledge_searched=True) == text


def test_citation_guard_chitchat_skipped():
    g = CoachGuardrails()
    assert g.apply_citation_guard("chitchat", [], "你好", knowledge_searched=True) == "你好"


def test_banned_diagnosis_detected_and_stripped():
    g = CoachGuardrails()
    text = "您这是确诊半月板损伤，需要处方。"
    assert g.contains_banned_diagnosis(text)
    cleaned = g.strip_banned_diagnosis(text)
    assert "确诊" not in cleaned
    assert "处方" not in cleaned


def test_ensure_disclaimer_appended():
    g = CoachGuardrails()
    out = g.ensure_disclaimer("建议低强度训练。")
    assert COACH_DISCLAIMER in out
    assert out.startswith("建议低强度训练。")


def test_dedupe_disclaimer():
    g = CoachGuardrails()
    doubled = f"正文\n\n{COACH_DISCLAIMER}\n\n{COACH_DISCLAIMER}"
    assert g.dedupe_disclaimer(doubled).count(COACH_DISCLAIMER) == 1


def test_apply_guardrails_full_pipeline():
    g = CoachGuardrails()
    text = "建议渐进负荷训练。"
    final, modified = g.apply_guardrails(
        text,
        intent="training",
        citations=[{"score": 0.5, "content": "训练"}],
        knowledge_searched=True,
    )
    assert COACH_DISCLAIMER in final
    assert modified is True


def test_apply_guardrails_citation_fail():
    g = CoachGuardrails()
    final, modified = g.apply_guardrails(
        "无依据回答",
        intent="nutrition",
        citations=[],
        knowledge_searched=True,
    )
    assert final == FALLBACK_NO_KNOWLEDGE
    assert modified is True


def test_redact_cot_traces():
    g = CoachGuardrails()
    traces = {"training": "用户可能确诊，需要开药。"}
    redacted = g.redact_cot_traces(traces)
    assert "确诊" not in redacted["training"]
    assert "开药" not in redacted["training"] or "【已省略】" in redacted["training"]
