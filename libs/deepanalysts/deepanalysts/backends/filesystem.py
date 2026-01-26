"""Local filesystem backend for reading files directly from disk.

This backend reads files from the local filesystem without any sandboxing.
Use for loading configuration files, memories, and skills from disk.
"""

from __future__ import annotations

import os
from pathlib import Path

from deepanalysts.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    GrepMatch,
    WriteResult,
)


class LocalFilesystemBackend(BackendProtocol):
    """Backend that reads/writes files directly to the local filesystem.

    Unlike RestrictedSubprocessBackend, this has no sandboxing - it operates
    directly on the local filesystem. Use for loading memories, skills, and
    configuration files.

    Example:
        ```python
        backend = LocalFilesystemBackend()
        content = backend.read("/home/user/.embient/AGENTS.md")
        ```
    """

    def __init__(
        self,
        root: str | Path | None = None,
        root_dir: str | Path | None = None,
        virtual_mode: bool = False,
    ) -> None:
        """Initialize the filesystem backend.

        Args:
            root: Optional root directory. If provided, all paths are relative to this.
                  If None, paths are treated as absolute or relative to cwd.
            root_dir: Alias for root (for backwards compatibility).
            virtual_mode: If True, paths are treated as virtual (prepended with root).
                         This is mainly for compatibility with embient.
        """
        effective_root = root or root_dir
        self._root = Path(effective_root).expanduser().resolve() if effective_root else None
        self._virtual_mode = virtual_mode

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path, expanding ~ and making absolute."""
        p = Path(path).expanduser()
        if self._root and not p.is_absolute():
            return self._root / p
        return p.resolve()

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files in a directory.

        Args:
            path: Directory path to list.

        Returns:
            List of FileInfo dicts with path and is_dir.
        """
        resolved = self._resolve_path(path)
        if not resolved.exists() or not resolved.is_dir():
            return []

        results: list[FileInfo] = []
        try:
            for entry in resolved.iterdir():
                results.append({
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                })
        except PermissionError:
            pass
        return results

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read file content with line numbers.

        Args:
            file_path: Path to file.
            offset: Line number to start from (0-indexed).
            limit: Max lines to read.

        Returns:
            File content with line numbers, or error message.
        """
        resolved = self._resolve_path(file_path)

        if not resolved.exists():
            return f"Error: File '{file_path}' not found"

        if not resolved.is_file():
            return f"Error: '{file_path}' is not a file"

        try:
            with open(resolved, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except PermissionError:
            return f"Error: Permission denied reading '{file_path}'"

        if not lines:
            return "System reminder: File exists but has empty contents"

        # Apply offset and limit
        selected = lines[offset : offset + limit]

        # Format with line numbers (cat -n style)
        output_lines = []
        for i, line in enumerate(selected):
            line_num = offset + i + 1
            line_content = line.rstrip("\n")
            output_lines.append(f"{line_num:6d}\t{line_content}")

        return "\n".join(output_lines)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Write content to a new file.

        Args:
            file_path: Path to create.
            content: Content to write.

        Returns:
            WriteResult with path or error.
        """
        resolved = self._resolve_path(file_path)

        if resolved.exists():
            return WriteResult(error=f"Error: File '{file_path}' already exists")

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            return WriteResult(path=str(resolved))
        except PermissionError:
            return WriteResult(error=f"Error: Permission denied writing '{file_path}'")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit file by replacing string.

        Args:
            file_path: Path to file.
            old_string: String to find.
            new_string: Replacement string.
            replace_all: Replace all occurrences.

        Returns:
            EditResult with path and count, or error.
        """
        resolved = self._resolve_path(file_path)

        if not resolved.exists():
            return EditResult(error=f"Error: File '{file_path}' not found")

        try:
            with open(resolved, encoding="utf-8") as f:
                content = f.read()
        except PermissionError:
            return EditResult(error=f"Error: Permission denied reading '{file_path}'")

        count = content.count(old_string)
        if count == 0:
            return EditResult(error=f"Error: String not found in file: '{old_string}'")
        if count > 1 and not replace_all:
            return EditResult(
                error=f"Error: String '{old_string}' appears {count} times. Use replace_all=True."
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            new_content = content.replace(old_string, new_string, 1)

        try:
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(new_content)
        except PermissionError:
            return EditResult(error=f"Error: Permission denied writing '{file_path}'")

        return EditResult(path=str(resolved), occurrences=count)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for pattern in files.

        Args:
            pattern: Literal string to search.
            path: Directory to search in.
            glob: File pattern to match.

        Returns:
            List of matches or error string.
        """
        search_path = self._resolve_path(path or ".")
        if not search_path.exists():
            return []

        matches: list[GrepMatch] = []
        glob_pattern = glob or "**/*"

        try:
            for file_path in search_path.glob(glob_pattern):
                if not file_path.is_file():
                    continue
                try:
                    with open(file_path, encoding="utf-8", errors="replace") as f:
                        for line_num, line in enumerate(f, 1):
                            if pattern in line:
                                matches.append({
                                    "path": str(file_path),
                                    "line": line_num,
                                    "text": line.rstrip("\n"),
                                })
                except (PermissionError, OSError):
                    continue
        except PermissionError:
            pass

        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching glob pattern.

        Args:
            pattern: Glob pattern.
            path: Base path.

        Returns:
            List of matching FileInfo.
        """
        search_path = self._resolve_path(path)
        if not search_path.exists():
            return []

        results: list[FileInfo] = []
        try:
            for match in search_path.glob(pattern):
                results.append({
                    "path": str(match),
                    "is_dir": match.is_dir(),
                })
        except PermissionError:
            pass

        return results

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download files (read as bytes).

        Args:
            paths: List of file paths.

        Returns:
            List of FileDownloadResponse with content or error.
        """
        responses: list[FileDownloadResponse] = []
        for path in paths:
            resolved = self._resolve_path(path)
            if not resolved.exists():
                responses.append(FileDownloadResponse(
                    path=path, content=None, error="file_not_found"
                ))
                continue
            try:
                content = resolved.read_bytes()
                responses.append(FileDownloadResponse(
                    path=path, content=content, error=None
                ))
            except PermissionError:
                responses.append(FileDownloadResponse(
                    path=path, content=None, error="permission_denied"
                ))
        return responses


# Alias for backwards compatibility with embient
FilesystemBackend = LocalFilesystemBackend

__all__ = ["LocalFilesystemBackend", "FilesystemBackend"]
