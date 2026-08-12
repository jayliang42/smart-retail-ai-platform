"""Request correlation shared by HTTP, Copilot, and tool execution logs."""

from contextvars import ContextVar, Token

_REQUEST_ID: ContextVar[str | None] = ContextVar("smart_retail_request_id", default=None)


def bind_request_id(request_id: str) -> Token[str | None]:
    return _REQUEST_ID.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _REQUEST_ID.reset(token)


def current_request_id() -> str | None:
    return _REQUEST_ID.get()
