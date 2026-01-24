"""Backends for deepanalysts middleware storage."""

from deepanalysts.backends.composite import CompositeBackend
from deepanalysts.backends.filesystem import FilesystemBackend, LocalFilesystemBackend
from deepanalysts.backends.protocol import (
    BACKEND_TYPES,
    BackendProtocol,
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    SandboxBackendProtocol,
    WriteResult,
)
from deepanalysts.backends.sandbox import BaseSandbox, RestrictedSubprocessBackend
from deepanalysts.backends.store import StoreBackend

__all__ = [
    # Protocols and types
    "BACKEND_TYPES",
    "BackendProtocol",
    "SandboxBackendProtocol",
    # Result types
    "EditResult",
    "ExecuteResponse",
    "FileDownloadResponse",
    "FileInfo",
    "FileUploadResponse",
    "GrepMatch",
    "WriteResult",
    # Backend implementations
    "BaseSandbox",
    "CompositeBackend",
    "FilesystemBackend",
    "LocalFilesystemBackend",
    "RestrictedSubprocessBackend",
    "StoreBackend",
]

# Optional imports that require additional dependencies (Basement API loaders)
try:
    from deepanalysts.backends.basement import BasementMemoryLoader, BasementSkillsLoader

    __all__.extend(["BasementMemoryLoader", "BasementSkillsLoader"])
except ImportError:
    pass
