import re
from pathlib import Path

from app.core.config import get_settings

COACH_DISCLAIMER = (
    "以上建议仅供参考，不能替代专业医疗诊断或治疗。"
    "如有持续疼痛、不适或红旗症状，请及时就医。"
)

FALLBACK_NO_KNOWLEDGE = (
    "抱歉，我在知识库中没有找到与您问题直接相关的说明。"
    "您可以补充更多细节，或咨询专业教练/医生进一步评估。"
)

CITATION_GUARD_INTENTS = frozenset({"training", "nutrition", "safety", "unknown"})

_BANNED_PATH = Path(__file__).resolve().parent.parent / "prompts" / "coach" / "banned_diagnosis.txt"


def load_banned_diagnosis_terms() -> list[str]:
    if not _BANNED_PATH.exists():
        return []
    terms: list[str] = []
    for line in _BANNED_PATH.read_text(encoding="utf-8").splitlines():
        term = line.strip()
        if term and not term.startswith("#"):
            terms.append(term)
    return terms


def collect_rag_citations(
    *,
    rag_citations: list[dict] | None = None,
    tool_calls: list[dict] | None = None,
) -> list[dict]:
    """Merge citations from state and successful knowledge_search tool results."""
    merged: list[dict] = list(rag_citations or [])
    seen = {c.get("chunk_id") for c in merged if c.get("chunk_id")}
    for tc in tool_calls or []:
        if tc.get("name") != "knowledge_search" or tc.get("status") == "error":
            continue
        result = tc.get("result")
        if not isinstance(result, dict):
            continue
        for citation in result.get("citations") or []:
            if not isinstance(citation, dict):
                continue
            chunk_id = citation.get("chunk_id")
            if chunk_id:
                if chunk_id in seen:
                    continue
                seen.add(chunk_id)
            merged.append(citation)
    return merged


class CoachGuardrails:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._banned_terms = load_banned_diagnosis_terms()

    @property
    def banned_terms(self) -> list[str]:
        return list(self._banned_terms)

    def citations_valid(self, citations: list[dict]) -> bool:
        if not citations:
            return False

        substantive = [c for c in citations if (c.get("content") or "").strip()]
        if not substantive:
            return False

        scores = sorted((float(c.get("score", 0)) for c in substantive), reverse=True)
        top = scores[0]
        if top <= 0:
            return False

        if top < self.settings.rag_score_floor:
            return False

        # Hybrid / keyword retrieval uses RRF-derived scores (~0.02–0.35), not cosine similarity.
        if any(c.get("source") in {"hybrid", "keyword"} for c in substantive):
            return True

        if top >= self.settings.rag_score_threshold:
            return True

        if len(scores) >= 2 and (top - scores[1]) >= self.settings.rag_score_min_gap:
            return True

        return len(substantive) == 1

    def contains_banned_diagnosis(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        return any(term.lower() in lowered for term in self._banned_terms)

    def strip_banned_diagnosis(self, text: str) -> str:
        result = text
        for term in self._banned_terms:
            result = re.sub(re.escape(term), "【已省略】", result, flags=re.IGNORECASE)
        return result

    def ensure_disclaimer(self, content: str) -> str:
        if COACH_DISCLAIMER in content:
            return content
        trimmed = content.rstrip()
        if trimmed:
            return f"{trimmed}\n\n{COACH_DISCLAIMER}"
        return COACH_DISCLAIMER

    def dedupe_disclaimer(self, content: str) -> str:
        while content.count(COACH_DISCLAIMER) > 1:
            first = content.find(COACH_DISCLAIMER)
            second = content.find(COACH_DISCLAIMER, first + len(COACH_DISCLAIMER))
            if second == -1:
                break
            content = content[:second] + content[second + len(COACH_DISCLAIMER) :]
        return content.strip()

    def apply_citation_guard(
        self,
        intent: str,
        citations: list[dict],
        content: str,
        *,
        knowledge_searched: bool = False,
    ) -> str:
        if intent not in CITATION_GUARD_INTENTS:
            return content
        if not knowledge_searched:
            return content
        if self.citations_valid(citations):
            return content
        return FALLBACK_NO_KNOWLEDGE

    def apply_guardrails(
        self,
        content: str,
        *,
        intent: str,
        citations: list[dict] | None = None,
        knowledge_searched: bool = False,
        append_disclaimer: bool = True,
    ) -> tuple[str, bool]:
        """Return (final_content, was_modified)."""
        original = content
        text = content

        if self.contains_banned_diagnosis(text):
            text = self.strip_banned_diagnosis(text)

        text = self.apply_citation_guard(
            intent,
            citations or [],
            text,
            knowledge_searched=knowledge_searched,
        )

        if append_disclaimer and text != FALLBACK_NO_KNOWLEDGE:
            if intent in CITATION_GUARD_INTENTS | {"recovery", "profile"}:
                text = self.ensure_disclaimer(text)
                text = self.dedupe_disclaimer(text)

        return text, text != original

    def redact_cot_traces(self, cot_traces: dict[str, str]) -> dict[str, str]:
        redacted: dict[str, str] = {}
        for key, value in cot_traces.items():
            cleaned = self.strip_banned_diagnosis(value)
            redacted[key] = cleaned
        return redacted
