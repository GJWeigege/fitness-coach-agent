from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.llm.dashscope_client import DashScopeClient

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = (
    "你是运动健康回复质量评审。根据用户问题、参考要点与 assistant 回复，"
    "判断回复是否忠实于参考（语义覆盖、无捏造诊断、无与参考明显矛盾）。"
    "仅返回 JSON：{\"faithful\": true|false, \"score\": 0.0~1.0}"
)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")


@dataclass
class FaithfulnessVerdict:
    faithful: bool
    score: float
    method: str


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    for piece in _TOKEN_RE.findall(text or ""):
        if len(piece) >= 2:
            tokens.add(piece.lower())
    for char in text or "":
        if "\u4e00" <= char <= "\u9fff":
            tokens.add(char)
    return tokens


def heuristic_faithfulness(*, reply: str, reference_answer: str) -> FaithfulnessVerdict:
    ref_tokens = _tokenize(reference_answer)
    reply_tokens = _tokenize(reply)
    if not ref_tokens:
        return FaithfulnessVerdict(faithful=True, score=1.0, method="heuristic_empty_ref")
    overlap = len(ref_tokens & reply_tokens) / len(ref_tokens)
    faithful = overlap >= 0.25
    return FaithfulnessVerdict(faithful=faithful, score=round(overlap, 4), method="heuristic")


def _parse_judge_json(content: str) -> FaithfulnessVerdict | None:
    text = (content or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group())
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    score = float(payload.get("score", 0.0))
    score = max(0.0, min(1.0, score))
    faithful = bool(payload.get("faithful", score >= 0.6))
    return FaithfulnessVerdict(faithful=faithful, score=round(score, 4), method="llm")


class FaithfulnessJudge:
    def __init__(self, llm_client: DashScopeClient | None = None) -> None:
        self.llm_client = llm_client

    async def evaluate(
        self,
        *,
        question: str,
        reply: str,
        reference_answer: str,
        use_llm: bool = True,
    ) -> FaithfulnessVerdict:
        if not reference_answer or not reference_answer.strip():
            return FaithfulnessVerdict(faithful=True, score=1.0, method="skipped_no_reference")

        if use_llm and self.llm_client is not None:
            user_payload = {
                "question": question,
                "reference_answer": reference_answer,
                "reply": reply[:6000],
            }
            try:
                result = await self.llm_client.chat(
                    [
                        {"role": "system", "content": _JUDGE_SYSTEM},
                        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                    ],
                    model=self.llm_client.settings.coach_router_model,
                )
                parsed = _parse_judge_json(result.content)
                if parsed is not None:
                    return parsed
            except Exception:
                logger.warning("faithfulness_llm_judge_failed", exc_info=True)

        return heuristic_faithfulness(reply=reply, reference_answer=reference_answer)
