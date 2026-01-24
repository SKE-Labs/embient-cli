"""Middleware for graceful tool error handling.

Catches ToolException and converts it to a ToolMessage so the LLM can
handle errors gracefully instead of crashing the graph.
"""

import logging
from collections.abc import Awaitable, Callable

from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException
from langgraph.types import Command

logger = logging.getLogger(__name__)


class ToolErrorHandlingMiddleware(AgentMiddleware):
    """Middleware that catches ToolException and converts it to a ToolMessage.

    This prevents tool errors from crashing the graph and allows the LLM to
    handle errors gracefully by seeing the error message and potentially
    retrying with different parameters or informing the user.

    Should be placed early in the middleware stack to catch errors from all tools.

    Example:
        ```python
        from langchain.agents import create_agent
        from embient.middleware import ToolErrorHandlingMiddleware

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

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Wrap tool calls to catch ToolException.

        Args:
            request: The tool call request being processed.
            handler: The handler function to call.

        Returns:
            The tool result or a ToolMessage with error content.
        """
        try:
            return handler(request)
        except ToolException as e:
            logger.warning(
                f"Tool '{request.tool_call['name']}' raised ToolException: {e}",
                extra={
                    "event": "tool_exception_caught",
                    "tool": request.tool_call["name"],
                    "error": str(e),
                },
            )
            return ToolMessage(
                content=f"Tool error: {e}",
                tool_call_id=request.tool_call["id"],
            )

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """(async) Wrap tool calls to catch ToolException.

        Args:
            request: The tool call request being processed.
            handler: The async handler function to call.

        Returns:
            The tool result or a ToolMessage with error content.
        """
        try:
            return await handler(request)
        except ToolException as e:
            logger.warning(
                f"Tool '{request.tool_call['name']}' raised ToolException: {e}",
                extra={
                    "event": "tool_exception_caught",
                    "tool": request.tool_call["name"],
                    "error": str(e),
                },
            )
            return ToolMessage(
                content=f"Tool error: {e}",
                tool_call_id=request.tool_call["id"],
            )
