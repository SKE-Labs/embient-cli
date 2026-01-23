"""Deep Analysts agent using LangChain create_agent + SubAgentMiddleware pattern.

This module provides a middleware-based approach to the trading analyst workflow,
using the `task` tool pattern instead of explicit StateGraph routing.
"""

from collections.abc import Sequence
from typing import Any

from deepagents.middleware import (
    FilesystemMiddleware,
    MemoryMiddleware,
    SkillsMiddleware,
)
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from embient.middleware import SubAgentMiddleware, ToolErrorHandlingMiddleware


SUPERVISOR_PROMPT = """# Embient AI Trading Analyst Supervisor

You are an orchestrator that delegates trading analysis to specialized analysts and synthesizes their outputs.

## Grounding Policy

IMPORTANT: You must NEVER:
- Invent price levels, stop losses, or take profits not derived from analysis
- Create signals without technical_analyst providing analysis first
- Guess position sizes — always use calculate_position_size via signal_manager
- Provide trade recommendations without disclaimer

All outputs must be grounded in subagent analysis and tool results.

## Professional Objectivity

Prioritize technical accuracy over validating user expectations:
- Never confirm user's bias without chart evidence
- Be direct about conflicting signals or low confidence
- Disagree with user's thesis if analysis contradicts it
- Objective guidance is more valuable than false agreement

## Delegation

Use the `task` tool to spawn specialized analysts:
- **technical_analyst** — charts, indicators, patterns, S/R levels (always first for trading)
- **signal_manager** — position sizing, signal creation (only after technical analysis)
- **fundamental_analyst** — news, sentiment, market events

## Workflow Rules

- **Analysis requests** → technical_analyst → respond
- **Signal creation** → technical_analyst → signal_manager → respond
- **Signal updates** → signal_manager → respond
- **News queries** → fundamental_analyst → respond
- **Full analysis** → technical + fundamental (PARALLEL) → respond

ALWAYS run technical analysis before signal creation. Parallelize independent analyses.
NEVER call the same subagent twice for the same query. Trust subagent outputs.

## Response Format

Keep responses concise:
- **Summary**: 1-2 sentences
- **Key Findings**: 3-5 bullets
- **Action**: If applicable

Use markdown. End trading advice with:
> **Disclaimer**: Educational only. Not financial advice. DYOR.
"""


def create_deep_analysts(
    model: BaseChatModel,
    tools: Sequence[BaseTool | dict[str, Any]] | None = None,
    *,
    system_prompt: str | None = None,
    checkpointer: Checkpointer | None = None,
    skills: list[str] | None = None,
    memory: list[str] | None = None,
    debug: bool = False,
) -> CompiledStateGraph:
    """Create a trading analyst agent with comprehensive middleware stack.

    This agent uses the `task` tool to delegate work to specialized analysts
    (technical_analyst, signal_manager, fundamental_analyst).

    Middleware order (orchestrator):
    1. ToolErrorHandlingMiddleware - Graceful error handling
    2. TodoListMiddleware - Planning & task tracking
    3. MemoryMiddleware - User preferences (if configured)
    4. SkillsMiddleware - Trading workflows (if configured)
    5. FilesystemMiddleware - Context management
    6. SubAgentMiddleware - Analyst delegation

    Subagents receive: ToolErrorHandlingMiddleware, SkillsMiddleware*, FilesystemMiddleware

    Args:
        model: The model to use for the orchestrator and subagents.
        tools: Additional tools to provide to the orchestrator.
        system_prompt: Override the default supervisor prompt.
        checkpointer: Optional checkpointer for state persistence.
        skills: Optional skill source paths (e.g., ["/skills/trading/"]).
        memory: Optional memory source paths (e.g., ["/memory/AGENTS.md"]).
        debug: Enable debug mode.

    Returns:
        A compiled agent graph.

    Usage:
        ```python
        from embient.analysts import create_deep_analysts
        from langchain_openai import ChatOpenAI

        model = ChatOpenAI(model="gpt-4o")
        agent = create_deep_analysts(
            model,
            checkpointer=memory_saver,
        )

        # Invoke with session context
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content="Analyze BTCUSDT")]},
            config={
                "configurable": {
                    "thread_id": "abc123",
                    "symbol": "BTC/USDT",
                    "exchange": "binance",
                    "interval": "4h",
                }
            }
        )
        ```
    """
    # Get analyst subagent definitions
    # Import here to avoid circular import
    from embient.analysts.fundamental import get_fundamental_analyst
    from embient.analysts.signal import get_signal_manager
    from embient.analysts.technical import get_technical_analyst

    subagents = [
        get_technical_analyst(model),
        get_fundamental_analyst(model),
        get_signal_manager(model),
    ]

    # Build subagent middleware factory
    def get_subagent_middleware(subagent_name: str) -> list[AgentMiddleware]:
        """Create middleware stack for a specific subagent.

        ToolErrorHandlingMiddleware is first to catch all tool errors before other
        middleware processes them.
        """
        subagent_middleware: list[AgentMiddleware] = [
            ToolErrorHandlingMiddleware(),  # First: catch all tool errors
        ]

        if skills:
            subagent_middleware.append(SkillsMiddleware(sources=skills))

        subagent_middleware.append(FilesystemMiddleware())
        return subagent_middleware

    # Build orchestrator middleware stack
    middleware: list[AgentMiddleware] = [
        ToolErrorHandlingMiddleware(),
        TodoListMiddleware(),
    ]

    if memory:
        middleware.append(MemoryMiddleware(sources=memory))

    if skills:
        middleware.append(SkillsMiddleware(sources=skills))

    middleware.extend(
        [
            FilesystemMiddleware(),
            SubAgentMiddleware(
                default_model=model,
                default_tools=tools or [],
                default_middleware_factory=get_subagent_middleware,
                subagents=subagents,
            ),
        ]
    )

    return create_agent(
        model,
        system_prompt=system_prompt or SUPERVISOR_PROMPT,
        tools=list(tools or []),
        middleware=middleware,
        checkpointer=checkpointer,
        debug=debug,
    ).with_config({"recursion_limit": 100})
