"""Composite backend that routes file operations by path prefix.

Routes operations to different backends based on path prefixes. Use this when you
need different storage strategies for different paths (e.g., sandbox for temp files,
persistent store for memories/skills).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import cast

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

# ---------------------------------------------------------------------------
# Module-level path helpers (ported from deepagents)
# ---------------------------------------------------------------------------


def _remap_grep_path(m: GrepMatch, route_prefix: str) -> GrepMatch:
    """Create a new GrepMatch with the route prefix prepended to the path."""
    return cast(
        "GrepMatch",
        {**m, "path": f"{route_prefix[:-1]}{m['path']}"},
    )


def _remap_file_info_path(fi: FileInfo, route_prefix: str) -> FileInfo:
    """Create a new FileInfo with the route prefix prepended to the path."""
    return cast(
        "FileInfo",
        {**fi, "path": f"{route_prefix[:-1]}{fi['path']}"},
    )


def _strip_route_from_pattern(pattern: str, route_prefix: str) -> str:
    """Strip a route prefix from a glob pattern when the pattern targets that route.

    If the pattern (ignoring a leading ``/``) starts with the route prefix
    (also ignoring its leading ``/``), the overlapping prefix is removed so
    the pattern is relative to the backend's internal root.
    """
    bare_pattern = pattern.lstrip("/")
    bare_prefix = route_prefix.strip("/") + "/"
    if bare_pattern.startswith(bare_prefix):
        return bare_pattern[len(bare_prefix) :]
    return pattern


def _route_for_path(
    *,
    default: BackendProtocol,
    sorted_routes: list[tuple[str, BackendProtocol]],
    path: str,
) -> tuple[BackendProtocol, str, str | None]:
    """Route a path to a backend and normalize it for that backend.

    Returns ``(backend, backend_path, matched_route_prefix | None)``.

    Normalization rules:
    - Exact route root without trailing slash (e.g. ``"/memories"``)
      → route to that backend with backend_path ``"/"``.
    - Path starts with route prefix (e.g. ``"/memories/notes.txt"``)
      → strip route prefix, ensure result starts with ``"/"``.
    - No match → default backend, original path.
    """
    for route_prefix, backend in sorted_routes:
        prefix_no_slash = route_prefix.rstrip("/")
        if path == prefix_no_slash:
            return backend, "/", route_prefix

        # Enforce boundary — require trailing / on the prefix for startswith
        normalized_prefix = route_prefix if route_prefix.endswith("/") else f"{route_prefix}/"
        if path.startswith(normalized_prefix):
            suffix = path[len(normalized_prefix) :]
            backend_path = f"/{suffix}" if suffix else "/"
            return backend, backend_path, route_prefix

    return default, path, None


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
            },
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
        self.default = default
        self.routes = routes
        self.sorted_routes = sorted(routes.items(), key=lambda x: len(x[0]), reverse=True)

    def _route(self, path: str) -> tuple[BackendProtocol, str, str | None]:
        """Route a path to the appropriate backend."""
        return _route_for_path(default=self.default, sorted_routes=self.sorted_routes, path=path)

    # ------------------------------------------------------------------
    # Sync protocol methods
    # ------------------------------------------------------------------

    def ls_info(self, path: str) -> list[FileInfo]:
        backend, backend_path, route_prefix = self._route(path)

        if route_prefix is not None:
            infos = backend.ls_info(backend_path)
            return [_remap_file_info_path(fi, route_prefix) for fi in infos]

        # At root, aggregate default and virtual route directories
        if path == "/":
            results: list[FileInfo] = list(self.default.ls_info(path))
            for rp, _b in self.sorted_routes:
                results.append({"path": rp, "is_dir": True, "size": 0, "modified_at": ""})
            results.sort(key=lambda x: x.get("path", ""))
            return results

        return self.default.ls_info(path)

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        backend, backend_path, _rp = self._route(file_path)
        return backend.read(backend_path, offset=offset, limit=limit)

    def write(self, file_path: str, content: str) -> WriteResult:
        backend, backend_path, _rp = self._route(file_path)
        return backend.write(backend_path, content)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        backend, backend_path, _rp = self._route(file_path)
        return backend.edit(backend_path, old_string, new_string, replace_all=replace_all)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        # If path targets a specific route, search only that backend
        if path is not None:
            for route_prefix, backend in self.sorted_routes:
                if path.startswith(route_prefix.rstrip("/")):
                    search_path = path[len(route_prefix) - 1 :] or "/"
                    raw = backend.grep_raw(pattern, search_path, glob)
                    if isinstance(raw, str):
                        return raw
                    return [_remap_grep_path(m, route_prefix) for m in raw]

        # Search default + all routed backends
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
                all_matches.extend(_remap_grep_path(m, route_prefix) for m in raw)

            return all_matches

        return self.default.grep_raw(pattern, path, glob)

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        for route_prefix, backend in self.sorted_routes:
            if path.startswith(route_prefix.rstrip("/")):
                search_path = path[len(route_prefix) - 1 :] or "/"
                stripped = _strip_route_from_pattern(pattern, route_prefix)
                infos = backend.glob_info(stripped, search_path)
                return [_remap_file_info_path(fi, route_prefix) for fi in infos]

        results: list[FileInfo] = list(self.default.glob_info(pattern, path))

        for route_prefix, backend in self.routes.items():
            stripped = _strip_route_from_pattern(pattern, route_prefix)
            infos = backend.glob_info(stripped, "/")
            results.extend(_remap_file_info_path(fi, route_prefix) for fi in infos)

        results.sort(key=lambda x: x.get("path", ""))
        return results

    def execute(self, command: str) -> ExecuteResponse:
        if isinstance(self.default, SandboxBackendProtocol):
            return self.default.execute(command)
        if hasattr(self.default, "execute"):
            return self.default.execute(command)
        raise NotImplementedError("Default backend doesn't support command execution (SandboxBackendProtocol).")

    async def aexecute(self, command: str) -> ExecuteResponse:
        if isinstance(self.default, SandboxBackendProtocol):
            return await self.default.aexecute(command)
        if hasattr(self.default, "aexecute"):
            return await self.default.aexecute(command)
        if hasattr(self.default, "execute"):
            return await asyncio.to_thread(self.default.execute, command)
        return await asyncio.to_thread(self.execute, command)

    @property
    def id(self) -> str:
        if isinstance(self.default, SandboxBackendProtocol):
            return f"composite-{self.default.id}"
        from uuid import uuid4

        return f"composite-{uuid4().hex[:8]}"

    # ------------------------------------------------------------------
    # Async overrides — delegate to the routed backend's native async
    # methods instead of falling through to asyncio.to_thread(sync)
    # which fails on async-only backends like SupabaseStorageBackend.
    # ------------------------------------------------------------------

    async def als_info(self, path: str) -> list[FileInfo]:
        backend, backend_path, route_prefix = self._route(path)

        if route_prefix is not None:
            infos = await backend.als_info(backend_path)
            return [_remap_file_info_path(fi, route_prefix) for fi in infos]

        if path == "/":
            results: list[FileInfo] = list(await self.default.als_info(path))
            for rp, _b in self.sorted_routes:
                results.append({"path": rp, "is_dir": True, "size": 0, "modified_at": ""})
            results.sort(key=lambda x: x.get("path", ""))
            return results

        return await self.default.als_info(path)

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        backend, backend_path, _rp = self._route(file_path)
        return await backend.aread(backend_path, offset=offset, limit=limit)

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        backend, backend_path, _rp = self._route(file_path)
        return await backend.awrite(backend_path, content)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        backend, backend_path, _rp = self._route(file_path)
        return await backend.aedit(backend_path, old_string, new_string, replace_all=replace_all)

    async def agrep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        if path is not None:
            for route_prefix, backend in self.sorted_routes:
                if path.startswith(route_prefix.rstrip("/")):
                    search_path = path[len(route_prefix) - 1 :] or "/"
                    raw = await backend.agrep_raw(pattern, search_path, glob)
                    if isinstance(raw, str):
                        return raw
                    return [_remap_grep_path(m, route_prefix) for m in raw]

        if path is None or path == "/":
            all_matches: list[GrepMatch] = []
            raw_default = await self.default.agrep_raw(pattern, path, glob)
            if isinstance(raw_default, str):
                return raw_default
            all_matches.extend(raw_default)

            for route_prefix, backend in self.routes.items():
                raw = await backend.agrep_raw(pattern, "/", glob)
                if isinstance(raw, str):
                    return raw
                all_matches.extend(_remap_grep_path(m, route_prefix) for m in raw)

            return all_matches

        return await self.default.agrep_raw(pattern, path, glob)

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        for route_prefix, backend in self.sorted_routes:
            if path.startswith(route_prefix.rstrip("/")):
                search_path = path[len(route_prefix) - 1 :] or "/"
                stripped = _strip_route_from_pattern(pattern, route_prefix)
                infos = await backend.aglob_info(stripped, search_path)
                return [_remap_file_info_path(fi, route_prefix) for fi in infos]

        results: list[FileInfo] = list(await self.default.aglob_info(pattern, path))

        for route_prefix, backend in self.routes.items():
            stripped = _strip_route_from_pattern(pattern, route_prefix)
            infos = await backend.aglob_info(stripped, "/")
            results.extend(_remap_file_info_path(fi, route_prefix) for fi in infos)

        results.sort(key=lambda x: x.get("path", ""))
        return results

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results: list[FileUploadResponse | None] = [None] * len(files)
        backend_batches: dict[int, list[tuple[int, str, bytes]]] = defaultdict(list)

        backends_by_id = {id(b): b for _, b in self.sorted_routes}
        backends_by_id[id(self.default)] = self.default

        for idx, (path, content) in enumerate(files):
            backend, stripped_path, _rp = self._route(path)
            backend_batches[id(backend)].append((idx, stripped_path, content))

        for backend_id, batch in backend_batches.items():
            backend = backends_by_id[backend_id]
            indices, stripped_paths, contents = zip(*batch, strict=False)
            batch_responses = await backend.aupload_files(list(zip(stripped_paths, contents, strict=False)))
            for i, orig_idx in enumerate(indices):
                results[orig_idx] = FileUploadResponse(
                    path=files[orig_idx][0],
                    error=(batch_responses[i].error if i < len(batch_responses) else None),
                )

        return results  # type: ignore[return-value]

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results: list[FileDownloadResponse | None] = [None] * len(paths)
        backend_batches: dict[int, list[tuple[int, str]]] = defaultdict(list)

        backends_by_id = {id(b): b for _, b in self.sorted_routes}
        backends_by_id[id(self.default)] = self.default

        for idx, path in enumerate(paths):
            backend, stripped_path, _rp = self._route(path)
            backend_batches[id(backend)].append((idx, stripped_path))

        for backend_id, batch in backend_batches.items():
            backend = backends_by_id[backend_id]
            indices, stripped_paths = zip(*batch, strict=False)
            batch_responses = await backend.adownload_files(list(stripped_paths))
            for i, orig_idx in enumerate(indices):
                results[orig_idx] = FileDownloadResponse(
                    path=paths[orig_idx],
                    content=(batch_responses[i].content if i < len(batch_responses) else None),
                    error=(batch_responses[i].error if i < len(batch_responses) else None),
                )

        return results  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Sync batch operations
    # ------------------------------------------------------------------

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        results: list[FileUploadResponse | None] = [None] * len(files)
        backend_batches: dict[BackendProtocol, list[tuple[int, str, bytes]]] = defaultdict(list)

        for idx, (path, content) in enumerate(files):
            backend, stripped_path, _rp = self._route(path)
            backend_batches[backend].append((idx, stripped_path, content))

        for backend, batch in backend_batches.items():
            indices, stripped_paths, contents = zip(*batch, strict=False)
            batch_responses = backend.upload_files(list(zip(stripped_paths, contents, strict=False)))
            for i, orig_idx in enumerate(indices):
                results[orig_idx] = FileUploadResponse(
                    path=files[orig_idx][0],
                    error=(batch_responses[i].error if i < len(batch_responses) else None),
                )

        return results  # type: ignore[return-value]

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        results: list[FileDownloadResponse | None] = [None] * len(paths)
        backend_batches: dict[BackendProtocol, list[tuple[int, str]]] = defaultdict(list)

        for idx, path in enumerate(paths):
            backend, stripped_path, _rp = self._route(path)
            backend_batches[backend].append((idx, stripped_path))

        for backend, batch in backend_batches.items():
            indices, stripped_paths = zip(*batch, strict=False)
            batch_responses = backend.download_files(list(stripped_paths))
            for i, orig_idx in enumerate(indices):
                results[orig_idx] = FileDownloadResponse(
                    path=paths[orig_idx],
                    content=(batch_responses[i].content if i < len(batch_responses) else None),
                    error=(batch_responses[i].error if i < len(batch_responses) else None),
                )

        return results  # type: ignore[return-value]
