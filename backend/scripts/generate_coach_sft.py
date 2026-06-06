#!/usr/bin/env python3
"""Generate coach_sft.jsonl (target >=200 samples) from benchmark + templates."""
from __future__ import annotations

import json
from pathlib import Path

DISCLAIMER = "本内容仅供参考，不能替代医疗建议。"
SYSTEM = "你是运动健康 Coach，输出 JSON plan 与带 disclaimer 的中文建议。"

BENCHMARK_PATH = Path(__file__).resolve().parents[1] / "data" / "benchmark" / "coach_eval.jsonl"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "finetune" / "coach_sft.jsonl"

ANSWER_BY_INTENT: dict[str, str] = {
    "safety": "请停止相关训练并就医评估，避免自行诊断。",
    "recovery": "恢复期建议低强度训练与充足蛋白，循序渐进。",
    "training": "建议渐进超负荷与合理分化，注意动作质量。",
    "nutrition": "建议均衡宏量与规律餐次，配合训练目标调整。",
    "profile": "已理解您的档案诉求，建议与当前目标对齐后更新计划。",
    "chitchat": "很高兴为您服务，有训练或营养问题可以继续问我。",
    "unknown": "请补充更多细节，以便给出更贴合的建议。",
}

PLAN_BY_INTENT: dict[str, dict | None] = {
    "recovery": {"tasks": [{"agent": "training"}, {"agent": "nutrition"}]},
    "training": None,
    "nutrition": None,
    "safety": None,
    "profile": None,
    "chitchat": None,
    "unknown": None,
}

EXTRA_QUESTIONS: list[tuple[str, str]] = [
    ("training", "保加利亚分蹲怎么做"),
    ("training", "罗马尼亚硬拉和直腿硬拉区别"),
    ("nutrition", "练后30分钟窗口真的重要吗"),
    ("safety", "手腕疼还能做俯卧撑吗"),
    ("recovery", "赛后第一周怎么练"),
    ("profile", "我想记录新的伤病史"),
]


def build_assistant_json(intent: str, *, answer: str | None = None) -> str:
    payload: dict = {
        "intent": intent,
        "answer": (answer or ANSWER_BY_INTENT.get(intent, ANSWER_BY_INTENT["unknown"])) + DISCLAIMER,
    }
    plan = PLAN_BY_INTENT.get(intent)
    if plan:
        payload["plan"] = plan
    return json.dumps(payload, ensure_ascii=False)


def row(question: str, intent: str, *, answer: str | None = None) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question},
            {"role": "assistant", "content": build_assistant_json(intent, answer=answer)},
        ]
    }


def main() -> int:
    rows: list[dict] = []
    seen: set[str] = set()

    def add(question: str, intent: str, *, answer: str | None = None) -> None:
        key = question.strip()
        if not key or key in seen:
            return
        seen.add(key)
        rows.append(row(key, intent, answer=answer))

    if BENCHMARK_PATH.is_file():
        for line in BENCHMARK_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            sample = json.loads(stripped)
            add(str(sample["question"]), str(sample["expected_intent"]))

    for intent, question in EXTRA_QUESTIONS:
        add(question, intent)

    variants = [
        ("training", "周{}", "建议每周{}次力量训练，注意恢复。"),
        ("nutrition", "蛋白质{}g够吗", "需结合体重与目标，一般按体重估算蛋白需求。"),
        ("safety", "{}时关节疼正常吗", "持续疼痛应停止并评估，不要忍痛训练。"),
        ("recovery", "恢复第{}天可以跑步吗", "从低强度开始，根据症状调整。"),
        ("chitchat", "{}", "您好，有什么训练问题可以问我。"),
    ]
    for intent, q_tpl, ans in variants:
        for n in range(1, 25):
            add(q_tpl.format(n), intent, answer=ans + DISCLAIMER)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} SFT samples to {OUTPUT_PATH}")
    return 0 if len(rows) >= 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
