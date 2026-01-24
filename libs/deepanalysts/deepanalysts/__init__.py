"""Deep Analysts - Middleware and backends for LangChain/LangGraph agents.

This package provides:
- Middleware for agent orchestration (subagents, memory, skills, filesystem, etc.)
- Backend implementations for file storage (store, sandbox, composite routing)
- Basement API client for syncing skills/memories
- Retry utilities for transient error handling

Usage:
    from deepanalysts.middleware import (
        FilesystemMiddleware,
        MemoryMiddleware,
        PatchToolCallsMiddleware,
        SkillsMiddleware,
        SubAgentMiddleware,
        SummarizationMiddleware,
        ToolErrorHandlingMiddleware,
    )
    from deepanalysts.backends import (
        CompositeBackend,
        StoreBackend,
        RestrictedSubprocessBackend,
    )
    from deepanalysts.clients import BasementClient
"""

from deepanalysts.middleware import (
    TASK_SYSTEM_PROMPT,
    TASK_TOOL_DESCRIPTION,
    CompiledSubAgent,
    FilesystemMiddleware,
    MemoryMiddleware,
    PatchToolCallsMiddleware,
    SkillMetadata,
    SkillsMiddleware,
    SubAgent,
    SubAgentMiddleware,
    SummarizationMiddleware,
    ToolErrorHandlingMiddleware,
    TruncateArgsSettings,
    build_session_context,
)

__all__ = [
    # Middleware classes
    "FilesystemMiddleware",
    "MemoryMiddleware",
    "PatchToolCallsMiddleware",
    "SkillsMiddleware",
    "SubAgentMiddleware",
    "SummarizationMiddleware",
    "ToolErrorHandlingMiddleware",
    # TypedDicts and types
    "CompiledSubAgent",
    "SkillMetadata",
    "SubAgent",
    "TruncateArgsSettings",
    # Constants
    "TASK_SYSTEM_PROMPT",
    "TASK_TOOL_DESCRIPTION",
    # Utility functions
    "build_session_context",
]

__version__ = "0.1.0"
