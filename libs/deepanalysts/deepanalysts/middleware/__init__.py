"""Middleware for Deep Analysts agent."""

from deepanalysts.middleware.filesystem import FilesystemMiddleware
from deepanalysts.middleware.memory import MemoryMiddleware
from deepanalysts.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepanalysts.middleware.skills import SkillMetadata, SkillsMiddleware
from deepanalysts.middleware.subagents import (
    TASK_SYSTEM_PROMPT,
    TASK_TOOL_DESCRIPTION,
    CompiledSubAgent,
    SubAgent,
    SubAgentMiddleware,
    build_session_context,
)
from deepanalysts.middleware.summarization import SummarizationMiddleware, TruncateArgsSettings
from deepanalysts.middleware.tool_errors import ToolErrorHandlingMiddleware

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
