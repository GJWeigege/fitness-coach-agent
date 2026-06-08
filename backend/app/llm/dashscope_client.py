import json
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.llm.tool_call_buffer import ToolCallBuffer

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# DashScope text-embedding-v3 rejects batches larger than 10 inputs.
_EMBEDDING_BATCH_SIZE = 10


@dataclass
class ChatResult:
    content: str
    model_name: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    tool_calls: list[dict] | None = None


@dataclass
class StreamDone:
    model_name: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class ToolCallComplete:
    id: str
    name: str
    arguments: dict


class DashScopeClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        if not settings.dashscope_api_key:
            raise ValueError("DASHSCOPE_API_KEY 未配置，请先在 .env 中设置。")
        self._client = httpx.AsyncClient(
            base_url=settings.dashscope_base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {settings.dashscope_api_key}",
                "Content-Type": "application/json",
            },
            timeout=settings.llm_request_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _resolve_model(self, model: str | None) -> str:
        return model or self.settings.coach_answer_model

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
    ) -> httpx.Response:
        max_attempts = 1 + self.settings.llm_max_retries
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                response = await self._client.request(method, path, json=json)
                if response.status_code in _RETRYABLE_STATUS and attempt < max_attempts - 1:
                    continue
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= max_attempts - 1:
                    raise
        if last_error:
            raise last_error
        raise RuntimeError("LLM request failed without a response")

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> ChatResult:
        payload: dict = {
            "model": self._resolve_model(model),
            "messages": messages,
            "temperature": 0.4,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        response = await self._request_with_retry("POST", "/chat/completions", json=payload)
        body = response.json()
        choice = body["choices"][0]
        message = choice["message"]
        usage = body.get("usage") or {}

        tool_calls = None
        raw_tool_calls = message.get("tool_calls")
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                args = tc.get("function", {}).get("arguments") or "{}"
                try:
                    parsed = json.loads(args)
                except json.JSONDecodeError:
                    parsed = {}
                tool_calls.append(
                    {
                        "id": tc.get("id", ""),
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": parsed,
                    }
                )

        return ChatResult(
            content=message.get("content") or "",
            model_name=body.get("model", self._resolve_model(model)),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            tool_calls=tool_calls,
        )

    async def embedding(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + _EMBEDDING_BATCH_SIZE]
            response = await self._request_with_retry(
                "POST",
                "/embeddings",
                json={
                    "model": self.settings.coach_embedding_model,
                    "input": batch,
                },
            )
            body = response.json()
            ordered = sorted(body["data"], key=lambda item: item["index"])
            vectors.extend(item["embedding"] for item in ordered)
        return vectors

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
    ) -> list[dict]:
        if not documents:
            return []

        payload = {
            "model": self.settings.coach_rerank_model,
            "input": {"query": query, "documents": documents},
            "parameters": {
                "return_documents": False,
                "top_n": top_n or len(documents),
            },
        }
        response = await self._request_with_retry_on_url(
            self.settings.dashscope_rerank_url,
            json=payload,
        )
        body = response.json()
        raw_results = body.get("output", {}).get("results")
        if raw_results is None:
            raw_results = body.get("results") or []

        ranked: list[dict] = []
        for item in raw_results:
            index = int(item["index"])
            if index < 0 or index >= len(documents):
                continue
            ranked.append(
                {
                    "index": index,
                    "relevance_score": float(item["relevance_score"]),
                }
            )
        ranked.sort(key=lambda item: item["relevance_score"], reverse=True)
        return ranked

    async def _request_with_retry_on_url(
        self,
        url: str,
        *,
        json: dict | None = None,
    ) -> httpx.Response:
        max_attempts = 1 + self.settings.llm_max_retries
        last_error: Exception | None = None
        headers = {
            "Authorization": f"Bearer {self.settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        for attempt in range(max_attempts):
            try:
                response = await self._client.post(url, json=json, headers=headers)
                if response.status_code in _RETRYABLE_STATUS and attempt < max_attempts - 1:
                    continue
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= max_attempts - 1:
                    raise
        if last_error:
            raise last_error
        raise RuntimeError("Rerank request failed without a response")

    async def chat_stream(self, messages: list[dict], *, model: str | None = None):
        async for item in self._stream_internal(messages, model=model, tools=None):
            yield item

    async def chat_stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
    ):
        async for item in self._stream_internal(messages, model=model, tools=tools):
            yield item

    async def _stream_internal(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        tools: list[dict] | None,
    ):
        payload: dict = {
            "model": self._resolve_model(model),
            "messages": messages,
            "temperature": 0.4,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        max_attempts = 1 + self.settings.llm_max_retries
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                async with self._client.stream("POST", "/chat/completions", json=payload) as response:
                    if response.status_code in _RETRYABLE_STATUS and attempt < max_attempts - 1:
                        await response.aread()
                        continue
                    response.raise_for_status()
                    async for item in self._parse_stream(response):
                        yield item
                    return
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= max_attempts - 1:
                    raise
        if last_error:
            raise last_error

    async def _parse_stream(self, response: httpx.Response):
        final_model = ""
        prompt_tokens = None
        completion_tokens = None
        total_tokens = None
        buffer = ToolCallBuffer()

        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if not data or data == "[DONE]":
                continue

            chunk = json.loads(data)
            if chunk.get("model"):
                final_model = chunk["model"]
            usage = chunk.get("usage")
            if usage:
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens")
                total_tokens = usage.get("total_tokens")

            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            text = delta.get("content")
            if text:
                yield text
            buffer.ingest_delta(delta.get("tool_calls"))

        for call in buffer.complete_calls():
            try:
                parsed = json.loads(call.arguments or "{}")
            except json.JSONDecodeError:
                parsed = {}
            yield ToolCallComplete(id=call.id or "", name=call.name, arguments=parsed)

        yield StreamDone(
            model_name=final_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
