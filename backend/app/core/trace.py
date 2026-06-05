import contextvars
import uuid

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def get_trace_id() -> str:
    value = trace_id_var.get()
    return value or ""


def set_trace_id(trace_id: str | None = None) -> str:
    tid = trace_id or str(uuid.uuid4())
    trace_id_var.set(tid)
    return tid
