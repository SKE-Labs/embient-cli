"""Tests for ToolErrorHandlingMiddleware error-message contract.

The middleware must mark failure ToolMessages with `status="error"` and
`name=tool_name` so downstream middleware can distinguish failed tool
invocations from successful ones without parsing content prefixes.
"""

from __future__ import annotations

import pytest
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException

from deepanalysts.middleware import ToolErrorHandlingMiddleware

pytest_plugins = ("anyio",)


def _request(tool_name: str, call_id: str = "c1") -> ToolCallRequest:
    return ToolCallRequest(
        tool_call={"name": tool_name, "args": {}, "id": call_id},
        tool=None,
        state={"messages": []},
        runtime=None,
    )


async def _raise_tool_exc(req: ToolCallRequest) -> ToolMessage:
    raise ToolException("boom")


async def _raise_unexpected(req: ToolCallRequest) -> ToolMessage:
    raise RuntimeError("unexpected")


async def _success(req: ToolCallRequest) -> ToolMessage:
    return ToolMessage(
        content="ok",
        name=req.tool_call["name"],
        tool_call_id=req.tool_call["id"],
    )


class TestErrorMessageStatus:
    @pytest.mark.anyio
    async def test_tool_exception_marks_status_error(self):
        mw = ToolErrorHandlingMiddleware()
        result = await mw.awrap_tool_call(_request("my_tool"), _raise_tool_exc)
        assert isinstance(result, ToolMessage)
        assert result.status == "error"
        assert result.name == "my_tool"
        assert result.content.startswith("Tool error:")

    @pytest.mark.anyio
    async def test_unexpected_exception_marks_status_error(self):
        mw = ToolErrorHandlingMiddleware()
        result = await mw.awrap_tool_call(_request("my_tool"), _raise_unexpected)
        assert result.status == "error"
        assert result.name == "my_tool"

    @pytest.mark.anyio
    async def test_circuit_breaker_stop_marks_status_error(self):
        """After max_retries failures, the next failure escalates to STOP:
        — that message must also be tagged status=error."""
        mw = ToolErrorHandlingMiddleware(max_retries=2)
        # Two failures to trip the breaker on the next failure-handling path.
        await mw.awrap_tool_call(_request("my_tool", "c1"), _raise_tool_exc)
        result = await mw.awrap_tool_call(_request("my_tool", "c2"), _raise_tool_exc)
        assert result.content.startswith("STOP:")
        assert result.status == "error"
        assert result.name == "my_tool"

    @pytest.mark.anyio
    async def test_blocked_message_marks_status_error(self):
        """Once the circuit is open, subsequent calls short-circuit to a
        BLOCKED message — that message must also be status=error."""
        mw = ToolErrorHandlingMiddleware(max_retries=1)
        # Trip the breaker.
        await mw.awrap_tool_call(_request("my_tool", "c1"), _raise_tool_exc)
        # This call is short-circuited via _blocked_message.
        result = await mw.awrap_tool_call(_request("my_tool", "c2"), _success)
        assert result.content.startswith("BLOCKED:")
        assert result.status == "error"
        assert result.name == "my_tool"

    @pytest.mark.anyio
    async def test_success_passes_through_unchanged(self):
        mw = ToolErrorHandlingMiddleware()
        result = await mw.awrap_tool_call(_request("my_tool"), _success)
        # Successful results are returned as-is — status defaults to success.
        assert result.status == "success"
        assert result.content == "ok"


class TestSyncPath:
    def test_sync_tool_exception_marks_status_error(self):
        mw = ToolErrorHandlingMiddleware()

        def raise_exc(req: ToolCallRequest) -> ToolMessage:
            raise ToolException("boom")

        result = mw.wrap_tool_call(_request("my_tool"), raise_exc)
        assert result.status == "error"
        assert result.name == "my_tool"
        assert result.content.startswith("Tool error:")
