from dataclasses import dataclass, field


@dataclass
class ToolCallState:
    id: str = ""
    name: str = ""
    arguments: str = ""


class ToolCallBuffer:
    def __init__(self) -> None:
        self._calls: dict[int, ToolCallState] = {}

    def ingest_delta(self, tool_calls: list | None) -> None:
        if not tool_calls:
            return
        for item in tool_calls:
            index = _get(item, "index", 0) or 0
            state = self._calls.setdefault(index, ToolCallState())
            item_id = _get(item, "id")
            if item_id:
                state.id = item_id
            fn = _get(item, "function")
            if fn is None:
                continue
            name = _get(fn, "name")
            if name:
                state.name = name
            arguments = _get(fn, "arguments")
            if arguments:
                state.arguments += arguments

    def complete_calls(self) -> list[ToolCallState]:
        return [self._calls[i] for i in sorted(self._calls.keys()) if self._calls[i].name]

    def reset(self) -> None:
        self._calls.clear()


def _get(obj, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
