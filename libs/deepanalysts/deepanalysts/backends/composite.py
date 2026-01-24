"""Composite backend that routes file operations by path prefix.

Routes operations to different backends based on path prefixes. Use this when you
need different storage strategies for different paths (e.g., sandbox for temp files,
persistent store for memories/skills).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from deepanalysts.backends.protocol import (
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

if TYPE_CHECKING:
    pass


class CompositeBackend(SandboxBackendProtocol):
    """Routes file operations to different backends by path prefix.

    Matches paths against route prefixes (longest first) and delegates to the
    corresponding backend. Unmatched paths use the default backend.

    Example:
        ```python
        composite = CompositeBackend(
            default=RestrictedSubprocessBackend(),
            routes={
                "/memories/": StoreBackend(rt),
                "/skills/": StoreBackend(rt),
            }
        )
        ```

    Attributes:
        default: Backend for paths that don't match any route.
        routes: Map of path prefixes to backends.
        sorted_routes: Routes sorted by length (longest first) for correct matching.
    """

    def __init__(
        self,
        default: BackendProtocol,
        routes: dict[str, BackendProtocol],
    ) -> None:
        """Initialize composite backend.

        Args:
            default: Backend for paths that don't match any route.
                    Should implement SandboxBackendProtocol for execute() support.
            routes: Map of path prefixes to backends. Prefixes must start with "/"
                and should end with "/" (e.g., "/memories/").
        """
        self.default = default
        self.routes = routes
        self.sorted_routes = sorted(
            routes.items(), key=lambda x: len(x[0]), reverse=True
        )

    def _get_backend_and_key(self, key: str) -> tuple[BackendProtocol, str]:
        """Get backend for path and strip route prefix.

        Returns:
            Tuple of (backend, stripped_path). The stripped path has the route
            prefix removed but keeps the leading slash.
        """
        for prefix, backend in self.sorted_routes:
            if key.startswith(prefix):
                suffix = key[len(prefix) :]
                stripped_key = f"/{suffix}" if suffix else "/"
                return backend, stripped_key

        return self.default, key

    def ls_info(self, path: str) -> list[FileInfo]:
        """List directory contents (non-recursive).

        If path matches a route, lists only that backend. If path is "/", aggregates
        default backend plus virtual route directories. Otherwise lists default backend.
        """
        # Check if path matches a specific route
        for route_prefix, backend in self.sorted_routes:
            if path.startswith(route_prefix.rstrip("/")):
                suffix = path[len(route_prefix) :]
                search_path = f"/{suffix}" if suffix else "/"
                infos = backend.ls_info(search_path)
                prefixed: list[FileInfo] = []
                for fi in infos:
                    fi = dict(fi)
                    fi["path"] = f"{route_prefix[:-1]}{fi['path']}"
                    prefixed.append(fi)
                return prefixed

        # At root, aggregate default and all routed backends
        if path == "/":
            results: list[FileInfo] = []
            results.extend(self.default.ls_info(path))
            for route_prefix, _backend in self.sorted_routes:
                results.append(
                    {"path": route_prefix, "is_dir": True, "size": 0, "modified_at": ""}
                )
            results.sort(key=lambda x: x.get("path", ""))
            return results

        return self.default.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file content, routing to appropriate backend."""
        backend, stripped_key = self._get_backend_and_key(file_path)
        return backend.read(stripped_key, offset=offset, limit=limit)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search files for pattern.

        Routes to backends based on path: specific route searches one backend,
        "/" or None searches all backends, otherwise searches default backend.
        """
        # If path targets a specific route, search only that backend
        for route_prefix, backend in self.sorted_routes:
            if path is not None and path.startswith(route_prefix.rstrip("/")):
                search_path = path[len(route_prefix) - 1 :]
                raw = backend.grep_raw(
                    pattern, search_path if search_path else "/", glob
                )
                if isinstance(raw, str):
                    return raw
                return [{**m, "path": f"{route_prefix[:-1]}{m['path']}"} for m in raw]

        # If path is None or "/", search default and all routed backends
        if path is None or path == "/":
            all_matches: list[GrepMatch] = []
            raw_default = self.default.grep_raw(pattern, path, glob)
            if isinstance(raw_default, str):
                return raw_default
            all_matches.extend(raw_default)

            for route_prefix, backend in self.routes.items():
                raw = backend.grep_raw(pattern, "/", glob)
                if isinstance(raw, str):
                    return raw
                all_matches.extend(
                    {**m, "path": f"{route_prefix[:-1]}{m['path']}"} for m in raw
                )

            return all_matches

        return self.default.grep_raw(pattern, path, glob)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching glob pattern."""
        results: list[FileInfo] = []

        for route_prefix, backend in self.sorted_routes:
            if path.startswith(route_prefix.rstrip("/")):
                search_path = path[len(route_prefix) - 1 :]
                infos = backend.glob_info(pattern, search_path if search_path else "/")
                return [
                    {**fi, "path": f"{route_prefix[:-1]}{fi['path']}"} for fi in infos
                ]

        results.extend(self.default.glob_info(pattern, path))

        for route_prefix, backend in self.routes.items():
            infos = backend.glob_info(pattern, "/")
            results.extend(
                {**fi, "path": f"{route_prefix[:-1]}{fi['path']}"} for fi in infos
            )

        results.sort(key=lambda x: x.get("path", ""))
        return results

    def write(self, file_path: str, content: str) -> WriteResult:
        """Create a new file, routing to appropriate backend."""
        backend, stripped_key = self._get_backend_and_key(file_path)
        return backend.write(stripped_key, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file, routing to appropriate backend."""
        backend, stripped_key = self._get_backend_and_key(file_path)
        return backend.edit(
            stripped_key, old_string, new_string, replace_all=replace_all
        )

    def execute(self, command: str) -> ExecuteResponse:
        """Execute shell command via default backend.

        The default backend must implement SandboxBackendProtocol.

        Raises:
            NotImplementedError: If default backend doesn't support execution.
        """
        if isinstance(self.default, SandboxBackendProtocol):
            return self.default.execute(command)

        raise NotImplementedError(
            "Default backend doesn't support command execution (SandboxBackendProtocol). "
            "Provide a default backend that implements SandboxBackendProtocol."
        )

    async def aexecute(self, command: str) -> ExecuteResponse:
        """Async version of execute."""
        if isinstance(self.default, SandboxBackendProtocol):
            return await self.default.aexecute(command)

        return await asyncio.to_thread(self.execute, command)

    @property
    def id(self) -> str:
        """Unique identifier for this composite backend instance.

        Delegates to default backend's ID if available, otherwise generates a unique one.
        """
        if isinstance(self.default, SandboxBackendProtocol):
            return f"composite-{self.default.id}"

        from uuid import uuid4

        return f"composite-{uuid4().hex[:8]}"

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files, batching by backend for efficiency."""
        results: list[FileUploadResponse | None] = [None] * len(files)
        backend_batches: dict[BackendProtocol, list[tuple[int, str, bytes]]] = (
            defaultdict(list)
        )

        for idx, (path, content) in enumerate(files):
            backend, stripped_path = self._get_backend_and_key(path)
            backend_batches[backend].append((idx, stripped_path, content))

        for backend, batch in backend_batches.items():
            indices, stripped_paths, contents = zip(*batch, strict=False)
            batch_files = list(zip(stripped_paths, contents, strict=False))
            batch_responses = backend.upload_files(batch_files)

            for i, orig_idx in enumerate(indices):
                results[orig_idx] = FileUploadResponse(
                    path=files[orig_idx][0],
                    error=(
                        batch_responses[i].error if i < len(batch_responses) else None
                    ),
                )

        return results  # type: ignore[return-value]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files, batching by backend for efficiency."""
        results: list[FileDownloadResponse | None] = [None] * len(paths)
        backend_batches: dict[BackendProtocol, list[tuple[int, str]]] = defaultdict(
            list
        )

        for idx, path in enumerate(paths):
            backend, stripped_path = self._get_backend_and_key(path)
            backend_batches[backend].append((idx, stripped_path))

        for backend, batch in backend_batches.items():
            indices, stripped_paths = zip(*batch, strict=False)
            batch_responses = backend.download_files(list(stripped_paths))

            for i, orig_idx in enumerate(indices):
                results[orig_idx] = FileDownloadResponse(
                    path=paths[orig_idx],
                    content=(
                        batch_responses[i].content if i < len(batch_responses) else None
                    ),
                    error=(
                        batch_responses[i].error if i < len(batch_responses) else None
                    ),
                )

        return results  # type: ignore[return-value]
