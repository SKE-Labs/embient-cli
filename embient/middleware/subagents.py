"""SubAgentMiddleware for orchestrating specialized subagents.

Provides the `task` tool for invoking subagents with automatic session context
injection (current datetime, symbol, exchange, interval).
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, cast

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, InterruptOnConfig
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain.tools import BaseTool, ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from embient.utils.retry import create_async_retry

logger = logging.getLogger(__name__)


class SubAgent(TypedDict):
    """Specification for a subagent."""

    name: str
    """The name of the agent (e.g., 'technical_analyst')."""

    description: str
    """Description used by supervisor to decide when to call this agent."""

    system_prompt: str
    """The system prompt for this agent."""

    tools: Sequence[BaseTool | Callable | dict[str, Any]]
    """Tools available to this agent."""

    model: NotRequired[str | BaseChatModel]
    """Model for this agent. Defaults to default_model."""

    middleware: NotRequired[list[AgentMiddleware]]
    """Additional middleware to apply."""

    interrupt_on: NotRequired[dict[str, bool | InterruptOnConfig]]
    """Tool interrupt configurations."""


class CompiledSubAgent(TypedDict):
    """A pre-compiled agent spec."""

    name: str
    description: str
    runnable: Runnable


DEFAULT_SUBAGENT_PROMPT = "Complete the task given to you using the available tools."

# State keys that are excluded when passing state to subagents and when returning
# updates from subagents.
_EXCLUDED_STATE_KEYS = {"messages", "todos", "structured_response"}


def _build_session_context(config: dict | None) -> str | None:
    """Build session context string from config.configurable.

    Extracts symbol, exchange, interval from config and includes current datetime.
    Returns None if no relevant session info is available.
    """
    if not config:
        return None

    configurable = config.get("configurable", {})
    symbol = configurable.get("symbol")
    exchange = configurable.get("exchange")
    interval = configurable.get("interval")

    if not any([symbol, exchange, interval]):
        return None

    current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = [f"## Session Context\n- **Current Time**: {current_time}"]

    if symbol:
        parts.append(f"- **Symbol**: {symbol}")
    if exchange:
        parts.append(f"- **Exchange**: {exchange}")
    if interval:
        parts.append(f"- **Interval**: {interval}")

    return "\n".join(parts)


TASK_TOOL_DESCRIPTION = """Launch a specialized subagent for specific tasks.

Available subagents:
{available_agents}

## When to Use

- Complex multi-step analysis requiring focused reasoning
- Independent research that can run in parallel
- Tasks requiring specialized tools

## When NOT to Use

- Simple operations (use tools directly)
- Redundant calls - if subagent already analyzed same context, reuse the result
- Follow-up questions where analysis already exists in conversation

## Task Description Format

Always include relevant context:
```
[Specific task or question]
[Include any relevant details from the conversation]
```

## Important

- Subagent results are invisible to user - YOU must synthesize and present
- Trust subagent outputs - they are specialized experts
- Parallelize independent analyses for speed
"""


TASK_SYSTEM_PROMPT = """## Subagent Delegation

Use `task` tool to spawn specialized subagents. Subagent results are invisible to user.

After subagents return:
- Synthesize findings into clear response
- Present to user with appropriate context
"""


def _create_subagents(
    *,
    default_model: str | BaseChatModel,
    default_tools: Sequence[BaseTool | Callable | dict[str, Any]],
    default_middleware: list[AgentMiddleware] | None,
    default_middleware_factory: Callable[[str], list[AgentMiddleware]] | None,
    default_interrupt_on: dict[str, bool | InterruptOnConfig] | None,
    subagents: list[SubAgent | CompiledSubAgent],
) -> tuple[dict[str, Any], list[str]]:
    """Create subagent instances from specifications."""
    default_subagent_middleware = default_middleware or []

    agents: dict[str, Any] = {}
    subagent_descriptions = []

    for agent_spec in subagents:
        subagent_descriptions.append(
            f"- {agent_spec['name']}: {agent_spec['description']}"
        )

        if "runnable" in agent_spec:
            # Pre-compiled agent
            compiled = cast("CompiledSubAgent", agent_spec)
            agents[compiled["name"]] = compiled["runnable"]
            continue

        # Build agent from spec
        _tools = agent_spec.get("tools", list(default_tools))
        _model = agent_spec.get("model", default_model)
        agent_name = agent_spec["name"]

        # Use factory for per-subagent middleware if provided, otherwise use default
        if default_middleware_factory:
            _middleware = default_middleware_factory(agent_name)
        else:
            _middleware = [*default_subagent_middleware]

        if "middleware" in agent_spec:
            _middleware.extend(agent_spec["middleware"])

        interrupt_on = agent_spec.get("interrupt_on", default_interrupt_on)
        if interrupt_on:
            _middleware.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))

        # Bind tags to model for streaming identification
        if hasattr(_model, "bind_config"):
            _model = _model.bind_config(tags=[agent_name])

        agents[agent_name] = create_agent(
            _model,
            system_prompt=agent_spec["system_prompt"],
            tools=_tools,
            middleware=_middleware,
        )

    return agents, subagent_descriptions


def _create_task_tool(
    *,
    default_model: str | BaseChatModel,
    default_tools: Sequence[BaseTool | Callable | dict[str, Any]],
    default_middleware: list[AgentMiddleware] | None,
    default_middleware_factory: Callable[[str], list[AgentMiddleware]] | None,
    default_interrupt_on: dict[str, bool | InterruptOnConfig] | None,
    subagents: list[SubAgent | CompiledSubAgent],
    task_description: str | None = None,
) -> BaseTool:
    """Create the task tool for invoking subagents."""
    subagent_graphs, subagent_descriptions = _create_subagents(
        default_model=default_model,
        default_tools=default_tools,
        default_middleware=default_middleware,
        default_middleware_factory=default_middleware_factory,
        default_interrupt_on=default_interrupt_on,
        subagents=subagents,
    )
    subagent_description_str = "\n".join(subagent_descriptions)

    if task_description is None:
        task_description = TASK_TOOL_DESCRIPTION.format(
            available_agents=subagent_description_str
        )
    elif "{available_agents}" in task_description:
        task_description = task_description.format(
            available_agents=subagent_description_str
        )

    def _return_command_with_state_update(result: dict, tool_call_id: str) -> Command:
        state_update = {
            k: v for k, v in result.items() if k not in _EXCLUDED_STATE_KEYS
        }
        # Strip trailing whitespace to prevent API errors
        message_text = (
            result["messages"][-1].text.rstrip() if result["messages"][-1].text else ""
        )
        return Command(
            update={
                **state_update,
                "messages": [ToolMessage(message_text, tool_call_id=tool_call_id)],
            }
        )

    def _validate_and_prepare_state(
        subagent_type: str, description: str, runtime: ToolRuntime
    ) -> tuple[Runnable, dict]:
        """Prepare state for invocation.

        Injects session context (current datetime, symbol, exchange, interval)
        from config.configurable into the task description so subagents have
        the necessary context for time-sensitive operations.
        """
        subagent = subagent_graphs[subagent_type]
        # Create a new state dict to avoid mutating the original
        subagent_state = {
            k: v for k, v in runtime.state.items() if k not in _EXCLUDED_STATE_KEYS
        }

        # Inject session context into the task description
        session_context = _build_session_context(runtime.config)
        if session_context:
            task_content = f"{session_context}\n\n## Task\n{description}"
        else:
            task_content = description

        subagent_state["messages"] = [HumanMessage(content=task_content)]
        return subagent, subagent_state

    def task(
        description: str,
        subagent_type: str,
        runtime: ToolRuntime,
    ) -> str | Command:
        """Invoke a subagent with the given task description."""
        if subagent_type not in subagent_graphs:
            allowed = ", ".join([f"`{k}`" for k in subagent_graphs])
            return f"Unknown subagent '{subagent_type}'. Available: {allowed}"

        subagent, subagent_state = _validate_and_prepare_state(
            subagent_type, description, runtime
        )
        result = subagent.invoke(subagent_state, runtime.config)

        if not runtime.tool_call_id:
            raise ValueError("Tool call ID is required for subagent invocation")

        return _return_command_with_state_update(result, runtime.tool_call_id)

    async def atask(
        description: str,
        subagent_type: str,
        runtime: ToolRuntime,
    ) -> str | Command:
        """Async invoke a subagent.

        Uses ainvoke() with tags for subagent identification in streams.
        Includes retry logic for transient API errors using centralized retry utility.
        """
        if subagent_type not in subagent_graphs:
            allowed = ", ".join([f"`{k}`" for k in subagent_graphs])
            return f"Unknown subagent '{subagent_type}'. Available: {allowed}"

        subagent, subagent_state = _validate_and_prepare_state(
            subagent_type, description, runtime
        )
        # Merge runtime config with tags for subagent identification in streams
        config = (
            {**runtime.config, "tags": [subagent_type]}
            if runtime.config
            else {"tags": [subagent_type]}
        )

        # Retry logic for transient API errors (5 attempts, exponential backoff 2s-16s)
        async for attempt in create_async_retry(
            max_attempts=5, min_wait=2.0, max_wait=16.0
        ):
            with attempt:
                result = await subagent.ainvoke(subagent_state, config)

        if not runtime.tool_call_id:
            raise ValueError("Tool call ID is required for subagent invocation")

        return _return_command_with_state_update(result, runtime.tool_call_id)

    return StructuredTool.from_function(
        name="task",
        func=task,
        coroutine=atask,
        description=task_description,
    )


class SubAgentMiddleware(AgentMiddleware):
    """Middleware that adds a `task` tool for invoking specialized subagents.

    Provides session context injection (datetime, symbol, exchange, interval) into
    subagent task descriptions for time-sensitive operations.

    Args:
        default_model: Model for subagents that don't specify one.
        default_tools: Default tools for subagents.
        default_middleware: Middleware to apply to all subagents (static list).
        default_middleware_factory: Factory function to create per-subagent middleware.
                                    Takes subagent name and returns middleware list.
                                    Takes precedence over default_middleware if provided.
        default_interrupt_on: Default interrupt configurations.
        subagents: List of SubAgent definitions.
        system_prompt: Additional system prompt instructions.
        task_description: Custom description for the task tool.
    """

    def __init__(
        self,
        *,
        default_model: str | BaseChatModel,
        default_tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
        default_middleware: list[AgentMiddleware] | None = None,
        default_middleware_factory: Callable[[str], list[AgentMiddleware]]
        | None = None,
        default_interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
        subagents: list[SubAgent | CompiledSubAgent] | None = None,
        system_prompt: str | None = TASK_SYSTEM_PROMPT,
        task_description: str | None = None,
    ) -> None:
        super().__init__()
        self.system_prompt = system_prompt

        task_tool = _create_task_tool(
            default_model=default_model,
            default_tools=default_tools or [],
            default_middleware=default_middleware,
            default_middleware_factory=default_middleware_factory,
            default_interrupt_on=default_interrupt_on,
            subagents=subagents or [],
            task_description=task_description,
        )
        self.tools = [task_tool]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Add task instructions to system prompt."""
        if self.system_prompt is not None:
            system_prompt = (
                request.system_prompt + "\n\n" + self.system_prompt
                if request.system_prompt
                else self.system_prompt
            )
            return handler(request.override(system_prompt=system_prompt))
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async: Add task instructions to system prompt."""
        if self.system_prompt is not None:
            system_prompt = (
                request.system_prompt + "\n\n" + self.system_prompt
                if request.system_prompt
                else self.system_prompt
            )
            return await handler(request.override(system_prompt=system_prompt))
        return await handler(request)
