import re
from pathlib import Path

REASONING_RE = re.compile(r"<reasoning>(.*?)</reasoning>", re.DOTALL | re.IGNORECASE)

_COT_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "coach" / "cot_instruction.txt"


def load_cot_instruction() -> str:
    return _COT_PROMPT_PATH.read_text(encoding="utf-8")


def split_cot(text: str) -> tuple[str | None, str]:
    match = REASONING_RE.search(text)
    if not match:
        return None, text.strip()
    reasoning = match.group(1).strip()
    answer = REASONING_RE.sub("", text).strip()
    return reasoning, answer
