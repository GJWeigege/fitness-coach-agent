import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.llm.dashscope_client import (
    ChatResult,
    DashScopeClient,
    StreamDone,
    ToolCallComplete,
)


@pytest.fixture
def llm_settings(monkeypatch):
    settings = Settings(
        dashscope_api_key="test-key",
        dashscope_base_url="https://dashscope.example/v1",
        coach_router_model="router-model",
        coach_answer_model="answer-model",
        coach_embedding_model="embed-model",
        llm_request_timeout_seconds=30,
        llm_max_retries=1,
    )
    monkeypatch.setattr("app.llm.dashscope_client.get_settings", lambda: settings)
    return settings


@pytest.fixture
def mock_async_client():
    with patch("app.llm.dashscope_client.httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client_cls.return_value = client
        yield client, client_cls


def _chat_response(**overrides) -> dict:
    body = {
        "model": "answer-model",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hello coach",
                }
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }
    body.update(overrides)
    return body


def _http_response(status_code: int, json_body: dict) -> httpx.Response:
    request = httpx.Request("POST", "https://dashscope.example/v1/chat/completions")
    return httpx.Response(status_code, json=json_body, request=request)


async def test_init_requires_api_key(monkeypatch):
    monkeypatch.setattr(
        "app.llm.dashscope_client.get_settings",
        lambda: Settings(dashscope_api_key=""),
    )
    with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
        DashScopeClient()


async def test_chat_success(mock_async_client, llm_settings):
    client, client_cls = mock_async_client
    http_response = _http_response(200, _chat_response())
    client.request = AsyncMock(return_value=http_response)

    dashscope = DashScopeClient()
    result = await dashscope.chat([{"role": "user", "content": "hi"}])

    assert isinstance(result, ChatResult)
    assert result.content == "Hello coach"
    assert result.model_name == "answer-model"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.total_tokens == 15
    assert result.tool_calls is None

    client_cls.assert_called_once()
    call_kwargs = client_cls.call_args.kwargs
    assert call_kwargs["base_url"] == "https://dashscope.example/v1"
    assert call_kwargs["timeout"] == 30
    assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"

    request_kwargs = client.request.call_args.kwargs
    assert request_kwargs["json"]["model"] == "answer-model"
    assert request_kwargs["json"]["messages"] == [{"role": "user", "content": "hi"}]


async def test_chat_uses_router_model_when_specified(mock_async_client, llm_settings):
    client, _ = mock_async_client
    client.request = AsyncMock(return_value=_http_response(200, _chat_response(model="router-model")))

    dashscope = DashScopeClient()
    await dashscope.chat([{"role": "user", "content": "route"}], model=llm_settings.coach_router_model)

    assert client.request.call_args.kwargs["json"]["model"] == "router-model"


async def test_chat_with_tools(mock_async_client, llm_settings):
    client, _ = mock_async_client
    body = _chat_response()
    body["choices"][0]["message"] = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "search_kb", "arguments": '{"query":"squat"}'},
            }
        ],
    }
    client.request = AsyncMock(return_value=_http_response(200, body))

    tools = [{"type": "function", "function": {"name": "search_kb", "parameters": {}}}]
    dashscope = DashScopeClient()
    result = await dashscope.chat([{"role": "user", "content": "hi"}], tools=tools)

    assert result.tool_calls == [
        {"id": "call_1", "name": "search_kb", "arguments": {"query": "squat"}}
    ]
    assert client.request.call_args.kwargs["json"]["tool_choice"] == "auto"


async def test_embedding(mock_async_client, llm_settings):
    client, _ = mock_async_client
    body = {
        "data": [
            {"index": 1, "embedding": [0.2, 0.4]},
            {"index": 0, "embedding": [0.1, 0.3]},
        ]
    }
    client.request = AsyncMock(return_value=_http_response(200, body))

    dashscope = DashScopeClient()
    vectors = await dashscope.embedding(["a", "b"])

    assert vectors == [[0.1, 0.3], [0.2, 0.4]]
    assert client.request.call_args.kwargs["json"]["model"] == "embed-model"
    assert client.request.call_args.kwargs["json"]["input"] == ["a", "b"]


async def test_embedding_batches_large_inputs(mock_async_client, llm_settings):
    client, _ = mock_async_client

    def _batch_response(batch: list[str]) -> httpx.Response:
        return _http_response(
            200,
            {
                "data": [
                    {"index": index, "embedding": [float(index)]}
                    for index in range(len(batch))
                ]
            },
        )

    client.request = AsyncMock(
        side_effect=[
            _batch_response([f"t{i}" for i in range(10)]),
            _batch_response([f"t{i}" for i in range(10, 12)]),
        ]
    )

    dashscope = DashScopeClient()
    vectors = await dashscope.embedding([f"t{i}" for i in range(12)])

    assert len(vectors) == 12
    assert vectors[0] == [0.0]
    assert vectors[11] == [1.0]
    assert client.request.await_count == 2
    assert len(client.request.call_args_list[0].kwargs["json"]["input"]) == 10
    assert len(client.request.call_args_list[1].kwargs["json"]["input"]) == 2


def _sse_lines(*events: dict) -> list[str]:
    lines = []
    for event in events:
        lines.append(f"data: {json.dumps(event)}")
    lines.append("data: [DONE]")
    return lines


async def _mock_stream_response(status_code: int, lines: list[str]):
    response = AsyncMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()

    async def aiter_lines():
        for line in lines:
            yield line

    response.aiter_lines = aiter_lines
    response.aread = AsyncMock(return_value=b"")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    return response


async def test_chat_stream(mock_async_client, llm_settings):
    client, _ = mock_async_client
    lines = _sse_lines(
        {"choices": [{"delta": {"content": "Hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}], "model": "answer-model"},
        {"usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}},
    )
    client.stream = MagicMock(return_value=await _mock_stream_response(200, lines))

    dashscope = DashScopeClient()
    chunks = []
    async for item in dashscope.chat_stream([{"role": "user", "content": "hi"}]):
        chunks.append(item)

    assert chunks[:-1] == ["Hel", "lo"]
    done = chunks[-1]
    assert isinstance(done, StreamDone)
    assert done.model_name == "answer-model"
    assert done.prompt_tokens == 3
    assert done.completion_tokens == 2
    assert done.total_tokens == 5


async def test_chat_stream_with_tools(mock_async_client, llm_settings):
    client, _ = mock_async_client
    lines = _sse_lines(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_abc",
                                "function": {"name": "plan_workout", "arguments": '{"day":'},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": '"legs"}'}}
                        ]
                    }
                }
            ],
            "model": "answer-model",
        },
    )
    client.stream = MagicMock(return_value=await _mock_stream_response(200, lines))

    tools = [{"type": "function", "function": {"name": "plan_workout", "parameters": {}}}]
    dashscope = DashScopeClient()
    chunks = []
    async for item in dashscope.chat_stream_with_tools(
        [{"role": "user", "content": "plan"}], tools
    ):
        chunks.append(item)

    tool_call = chunks[0]
    assert isinstance(tool_call, ToolCallComplete)
    assert tool_call.id == "call_abc"
    assert tool_call.name == "plan_workout"
    assert tool_call.arguments == {"day": "legs"}
    assert isinstance(chunks[-1], StreamDone)


async def test_chat_retries_on_503(mock_async_client, llm_settings):
    client, _ = mock_async_client
    fail = _http_response(503, {"error": "busy"})
    ok = _http_response(200, _chat_response())
    client.request = AsyncMock(side_effect=[fail, ok])

    dashscope = DashScopeClient()
    result = await dashscope.chat([{"role": "user", "content": "hi"}])

    assert result.content == "Hello coach"
    assert client.request.await_count == 2


async def test_chat_retries_on_timeout(mock_async_client, llm_settings):
    client, _ = mock_async_client
    ok = _http_response(200, _chat_response())
    client.request = AsyncMock(
        side_effect=[httpx.TimeoutException("timeout"), ok],
    )

    dashscope = DashScopeClient()
    result = await dashscope.chat([{"role": "user", "content": "hi"}])

    assert result.content == "Hello coach"
    assert client.request.await_count == 2


async def test_chat_exhausts_retries(mock_async_client, llm_settings):
    client, _ = mock_async_client
    client.request = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    dashscope = DashScopeClient()
    with pytest.raises(httpx.TimeoutException):
        await dashscope.chat([{"role": "user", "content": "hi"}])

    assert client.request.await_count == 2


async def test_get_settings_cached():
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.coach_answer_model == "qwen-plus"
    get_settings.cache_clear()
