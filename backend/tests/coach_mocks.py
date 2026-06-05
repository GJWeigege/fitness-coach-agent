from app.llm.dashscope_client import ChatResult, StreamDone, ToolCallComplete


class MockDashScopeClient:
    def __init__(
        self,
        *,
        chat_responses: list[str | ChatResult] | None = None,
        stream_chunks: list[str | ToolCallComplete] | None = None,
        tool_stream_chunks: list[str | ToolCallComplete] | None = None,
    ) -> None:
        self.chat_responses = list(chat_responses or [])
        self.stream_chunks = list(stream_chunks or [])
        self.tool_stream_chunks = list(tool_stream_chunks or [])
        self.chat_calls: list[tuple[list[dict], dict]] = []
        self.stream_calls: list[tuple[list[dict], dict]] = []
        self.tool_stream_calls: list[tuple[list[dict], list[dict], dict]] = []
        self.settings = type(
            "S",
            (),
            {
                "coach_router_model": "router-model",
                "coach_answer_model": "answer-model",
                "coach_planner_model": "planner-model",
            },
        )()

    def _chat_result(self, content: str) -> ChatResult:
        return ChatResult(
            content=content,
            model_name="mock-model",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        )

    async def chat(self, messages, *, model=None, tools=None, tool_choice=None):
        self.chat_calls.append((messages, {"model": model, "tools": tools, "tool_choice": tool_choice}))
        if self.chat_responses:
            item = self.chat_responses.pop(0)
            if isinstance(item, ChatResult):
                return item
            return self._chat_result(item)
        return self._chat_result("mock chat response")

    async def chat_stream(self, messages, *, model=None):
        self.stream_calls.append((messages, {"model": model}))
        for chunk in self.stream_chunks:
            if isinstance(chunk, (StreamDone, ToolCallComplete)):
                yield chunk
            else:
                yield chunk
        yield StreamDone(model_name="mock-model")

    async def chat_stream_with_tools(self, messages, tools, *, model=None):
        self.tool_stream_calls.append((messages, tools, {"model": model}))
        if self.tool_stream_chunks:
            chunks = self.tool_stream_chunks
            self.tool_stream_chunks = []
        else:
            chunks = self.stream_chunks
        for chunk in chunks:
            yield chunk
        yield StreamDone(model_name="mock-model")
