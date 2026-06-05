from app.agent.coach.cot import load_cot_instruction, split_cot


def test_cot_instruction_loads():
    text = load_cot_instruction()
    assert "<reasoning>" in text


def test_split_cot_no_tags():
    reasoning, answer = split_cot("直接回答用户。")
    assert reasoning is None
    assert answer == "直接回答用户。"


def test_split_cot_with_reasoning():
    raw = "<reasoning>需要先查知识库。</reasoning>\n\n建议先做热身。"
    reasoning, answer = split_cot(raw)
    assert reasoning == "需要先查知识库。"
    assert answer == "建议先做热身。"


def test_split_cot_case_insensitive():
    raw = "<REASONING>思考</REASONING>最终答案"
    reasoning, answer = split_cot(raw)
    assert reasoning == "思考"
    assert answer == "最终答案"


def test_split_cot_strips_whitespace():
    raw = "  <reasoning>  内层  </reasoning>  \n  外层  "
    reasoning, answer = split_cot(raw)
    assert reasoning == "内层"
    assert answer == "外层"
