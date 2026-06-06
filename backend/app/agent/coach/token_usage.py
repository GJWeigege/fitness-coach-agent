import uuid


def accumulate_tokens(
    run_meta: dict | None,
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> None:
    if not isinstance(run_meta, dict):
        return
    if prompt_tokens is not None:
        run_meta["prompt_tokens"] = int(run_meta.get("prompt_tokens") or 0) + prompt_tokens
    if completion_tokens is not None:
        run_meta["completion_tokens"] = int(run_meta.get("completion_tokens") or 0) + completion_tokens


def token_totals(run_meta: dict) -> tuple[int | None, int | None]:
    prompt = run_meta.get("prompt_tokens")
    completion = run_meta.get("completion_tokens")
    if prompt is None and completion is None:
        return None, None
    return prompt, completion


def combined_total_tokens(prompt: int | None, completion: int | None) -> int | None:
    if prompt is None and completion is None:
        return None
    return (prompt or 0) + (completion or 0)


def merge_token_counts(
    prompt: int | None,
    completion: int | None,
    extra_prompt: int | None,
    extra_completion: int | None,
) -> tuple[int | None, int | None]:
    if extra_prompt is None and extra_completion is None:
        return prompt, completion
    return (
        (prompt or 0) + (extra_prompt or 0),
        (completion or 0) + (extra_completion or 0),
    )


async def track_llm_usage(
    conf: dict,
    *,
    run_id: str | uuid.UUID,
    purpose: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int | None = None,
    step_id: uuid.UUID | None = None,
) -> None:
    accumulate_tokens(
        conf.get("run_meta"),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    observability = conf.get("observability")
    db = conf.get("db")
    if observability is None or db is None:
        return
    await observability.record_llm_call(
        db,
        uuid.UUID(str(run_id)),
        purpose=purpose,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        step_id=step_id,
    )
