"""Middleware for graceful tool error handling with circuit breaker.

Catches ToolException and converts it to a ToolMessage so the LLM can
handle errors gracefully instead of crashing the graph. Tracks consecutive
failures per tool and blocks tools that fail repeatedly.
"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ToolErrorHandlingMiddleware(AgentMiddleware):
    """Middleware that catches tool errors with circuit breaker protection.

    Tracks consecutive failures per tool name. After ``max_retries``
    consecutive failures of the same tool, subsequent calls are
    short-circuited without executing the handler. All failure counters
    reset when any tool succeeds.

    Should be placed early in the middleware stack to catch errors from all tools.

    Args:
        max_retries: Maximum consecutive failures before blocking a tool.
            Defaults to 3.

    Example:
        ```python
        from langchain.agents import create_agent
        from deepanalysts.middleware import ToolErrorHandlingMiddleware

        agent = create_agent(
            model,
            tools=[...],
            middleware=[
                ToolErrorHandlingMiddleware(),  # First to catch all errors
                ...other middleware...
            ],
        )
        ```
    """

    def __init__(self, *, max_retries: int = 3) -> None:
        super().__init__()
        self.max_retries = max_retries
        self._failure_counts: dict[str, int] = {}

    def _on_success(self) -> None:
        """Reset all failure counters when any tool succeeds."""
        if self._failure_counts:
            self._failure_counts.clear()

    def _on_failure(self, tool_name: str, error: str, tool_call_id: str) -> ToolMessage:
        """Track failure and return an appropriate (possibly escalated) error message.

        The returned ToolMessage carries `status="error"` and `name=tool_name`
        so downstream middleware (and any caller scanning history) can
        distinguish failed invocations from successful ones without parsing
        content prefixes.
        """
        count = self._failure_counts.get(tool_name, 0) + 1
        self._failure_counts[tool_name] = count

        if count >= self.max_retries:
            content = (
                f"STOP: Tool '{tool_name}' has failed {count} times consecutively. "
                f"Do NOT retry this tool. Report the failure to the user and "
                f"continue without it. Last error: {error}"
            )
        else:
            content = f"Tool error: {error}"

        return ToolMessage(
            content=content,
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )

    def _blocked_message(self, tool_name: str, tool_call_id: str) -> ToolMessage:
        """Return a message for tools that have already been blocked."""
        count = self._failure_counts[tool_name]
        self._failure_counts[tool_name] = count + 1
        return ToolMessage(
            content=(
                f"BLOCKED: Tool '{tool_name}' was disabled after {self.max_retries} "
                f"consecutive failures (attempt {count + 1}). Do NOT call this tool "
                f"again. Inform the user and proceed with available information."
            ),
            tool_call_id=tool_call_id,
            name=tool_name,
            status="error",
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        tool_name = request.tool_call["name"]
        tool_call_id = request.tool_call["id"]

        if self._failure_counts.get(tool_name, 0) >= self.max_retries:
            return self._blocked_message(tool_name, tool_call_id)

        try:
            result = handler(request)
            self._on_success()
            return result
        except ToolException as e:
            logger.warning(
                f"Tool '{tool_name}' raised ToolException: {e}",
                extra={
                    "event": "tool_exception_caught",
                    "tool": tool_name,
                    "error": str(e),
                },
            )
            return self._on_failure(tool_name, str(e), tool_call_id)
        except Exception as e:
            logger.error(
                f"Tool '{tool_name}' raised unexpected error: {e}",
                exc_info=True,
                extra={
                    "event": "tool_unexpected_error",
                    "tool": tool_name,
                    "error": str(e),
                },
            )
            return self._on_failure(tool_name, str(e), tool_call_id)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        tool_name = request.tool_call["name"]
        tool_call_id = request.tool_call["id"]

        if self._failure_counts.get(tool_name, 0) >= self.max_retries:
            return self._blocked_message(tool_name, tool_call_id)

        try:
            result = await handler(request)
            self._on_success()
            return result
        except ToolException as e:
            logger.warning(
                f"Tool '{tool_name}' raised ToolException: {e}",
                extra={
                    "event": "tool_exception_caught",
                    "tool": tool_name,
                    "error": str(e),
                },
            )
            return self._on_failure(tool_name, str(e), tool_call_id)
        except Exception as e:
            logger.error(
                f"Tool '{tool_name}' raised unexpected error: {e}",
                exc_info=True,
                extra={
                    "event": "tool_unexpected_error",
                    "tool": tool_name,
                    "error": str(e),
                },
            )
            return self._on_failure(tool_name, str(e), tool_call_id)
