"""SupabaseStorageBackend: S3-compatible object store via Supabase Storage REST API.

Maps virtual file paths to Supabase Storage objects within a user-scoped prefix.
All operations are async-native via httpx. Sync methods raise NotImplementedError.

Path resolution example (with path_prefix="skills"):
    Virtual:  /trend-following/SKILL.md      (after CompositeBackend strips route)
    Storage:  {user_id}/skills/trend-following/SKILL.md
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from deepanalysts.backends.protocol import (
    BackendProtocol,
    EditResult,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    WriteResult,
)
from deepanalysts.backends.utils import (
    _get_file_type,
    _glob_search_files,
    format_read_response,
    grep_matches_from_files,
    perform_string_replacement,
)

# Concurrency limit for parallel downloads (grep, glob, batch)
_DOWNLOAD_SEMAPHORE_LIMIT = 10

# Supabase Storage list endpoint returns at most this many items per call
_LIST_PAGE_SIZE = 1000


def _not_implemented(method: str) -> NotImplementedError:
    return NotImplementedError(
        f"SupabaseStorageBackend.{method}() is async-only. Use the async variant (a{method}) instead."
    )


class SupabaseStorageBackend(BackendProtocol):
    """Backend that stores files in Supabase Storage (S3-compatible object store).

    Uses ``httpx.AsyncClient`` directly against the Supabase Storage REST API.
    Park uses the Supabase ``service_role`` key which bypasses RLS.

    Args:
        supabase_url: Supabase project URL (e.g. ``https://xxx.supabase.co``).
        supabase_key: Service role key (bypasses RLS).
        bucket: Storage bucket name. Defaults to ``"user-files"``.
        user_id: Static user ID for path scoping.
        user_id_factory: Callable that returns user ID at call time
            (for per-request resolution). Exactly one of ``user_id`` or
            ``user_id_factory`` must be provided.
        path_prefix: Category prefix inserted between user_id and virtual path.
            E.g. ``"skills"`` maps virtual ``/foo/SKILL.md`` to storage
            ``{user_id}/skills/foo/SKILL.md``.
    """

    def __init__(
        self,
        *,
        supabase_url: str,
        supabase_key: str,
        bucket: str = "user-files",
        user_id: str | None = None,
        user_id_factory: Callable[[], str] | None = None,
        path_prefix: str = "",
    ) -> None:
        self._base_url = supabase_url.rstrip("/")
        self._key = supabase_key
        self._bucket = bucket
        self._user_id = user_id
        self._user_id_factory = user_id_factory
        self._path_prefix = path_prefix.strip("/")
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_uid(self) -> str:
        if self._user_id:
            return self._user_id
        if self._user_id_factory is not None:
            uid = self._user_id_factory()
            if uid:
                return uid
        msg = (
            "SupabaseStorageBackend: user_id is not available. "
            "Provide user_id or user_id_factory that returns a non-empty string."
        )
        raise ValueError(msg)

    def _storage_path(self, virtual_path: str) -> str:
        """Map virtual path to storage object path."""
        uid = self._get_uid()
        clean = virtual_path.strip("/")
        if self._path_prefix:
            return f"{uid}/{self._path_prefix}/{clean}" if clean else f"{uid}/{self._path_prefix}"
        return f"{uid}/{clean}" if clean else uid

    def _storage_prefix(self, virtual_path: str) -> str:
        """Map virtual path to storage prefix for listing (ensures trailing slash)."""
        p = self._storage_path(virtual_path)
        return p if p.endswith("/") else p + "/"

    def _to_virtual(self, full_storage_path: str) -> str:
        """Strip user/prefix portion to recover the virtual path."""
        uid = self._get_uid()
        base = f"{uid}/{self._path_prefix}/" if self._path_prefix else f"{uid}/"
        if full_storage_path.startswith(base):
            return "/" + full_storage_path[len(base) :]
        # Fallback — shouldn't happen with well-formed paths
        return "/" + full_storage_path.rsplit("/", 1)[-1]

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "apikey": self._key,
                },
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying httpx client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _download_raw(self, storage_path: str) -> httpx.Response:
        """Download a single file by storage path. Returns the raw httpx.Response."""
        client = await self._get_client()
        return await client.get(
            f"{self._base_url}/storage/v1/object/{self._bucket}/{storage_path}",
        )

    async def _list_objects(
        self,
        prefix: str,
        *,
        recursive: bool = False,
    ) -> list[dict[str, Any]]:
        """List all objects under a prefix with automatic pagination.

        When ``recursive=True``, descends into sub-folders in parallel.
        """
        client = await self._get_client()
        all_items: list[dict[str, Any]] = []
        offset = 0

        while True:
            resp = await client.post(
                f"{self._base_url}/storage/v1/object/list/{self._bucket}",
                json={
                    "prefix": prefix,
                    "limit": _LIST_PAGE_SIZE,
                    "offset": offset,
                    "sortBy": {"column": "name", "order": "asc"},
                },
            )
            if resp.status_code != 200:
                break

            items = resp.json()
            if not items:
                break

            if recursive:
                # Supabase list is non-recursive — folders have id=null.
                # Descend into folders in parallel for efficiency.
                folder_tasks = []
                for item in items:
                    if item.get("id") is None:
                        folder_prefix = f"{prefix}{item['name']}/"
                        folder_tasks.append(self._list_objects(folder_prefix, recursive=True))
                    else:
                        item["_full_prefix"] = prefix
                        all_items.append(item)

                if folder_tasks:
                    folder_results = await asyncio.gather(*folder_tasks)
                    for sub_items in folder_results:
                        all_items.extend(sub_items)
            else:
                all_items.extend(items)

            if len(items) < _LIST_PAGE_SIZE:
                break
            offset += _LIST_PAGE_SIZE

        return all_items

    def _content_type(self, path: str) -> str:
        """Guess Content-Type from file extension."""
        mime, _ = mimetypes.guess_type(path)
        if mime:
            return mime
        if path.endswith(".md"):
            return "text/markdown; charset=utf-8"
        return "text/plain; charset=utf-8"

    # ------------------------------------------------------------------
    # Async protocol methods
    # ------------------------------------------------------------------

    async def als_info(self, path: str) -> list[FileInfo]:
        """List directory contents (non-recursive)."""
        prefix = self._storage_prefix(path)
        items = await self._list_objects(prefix, recursive=False)

        entries: list[FileInfo] = []
        for item in items:
            name = item.get("name", "")
            if not name:
                continue

            if item.get("id") is None:
                entries.append(FileInfo(path=f"/{name}/", is_dir=True, size=0, modified_at=""))
            else:
                metadata = item.get("metadata") or {}
                entries.append(
                    FileInfo(
                        path=f"/{name}",
                        is_dir=False,
                        size=metadata.get("size", 0),
                        modified_at=item.get("updated_at", ""),
                    )
                )

        entries.sort(key=lambda x: x.get("path", ""))
        return entries

    async def aread(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Download and return file content formatted with line numbers."""
        storage_path = self._storage_path(file_path)
        resp = await self._download_raw(storage_path)

        if resp.status_code in (400, 404):
            return f"Error: File '{file_path}' not found"
        if resp.status_code != 200:
            return f"Error: Failed to read '{file_path}' (HTTP {resp.status_code})"

        now = datetime.now(UTC).isoformat()

        if _get_file_type(file_path) != "text":
            b64 = base64.standard_b64encode(resp.content).decode("ascii")
            return format_read_response(
                {"content": b64, "encoding": "base64", "created_at": now, "modified_at": now},
                offset,
                limit,
            )

        try:
            text = resp.content.decode("utf-8")
        except UnicodeDecodeError:
            b64 = base64.standard_b64encode(resp.content).decode("ascii")
            return format_read_response(
                {"content": b64, "encoding": "base64", "created_at": now, "modified_at": now},
                offset,
                limit,
            )

        return format_read_response(
            {"content": text, "encoding": "utf-8", "created_at": now, "modified_at": now},
            offset,
            limit,
        )

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        """Create a new file. Returns error if file already exists (400 from Supabase)."""
        client = await self._get_client()
        storage_path = self._storage_path(file_path)
        content_type = self._content_type(file_path)

        # POST without x-upsert — Supabase returns 400 if the file exists.
        resp = await client.post(
            f"{self._base_url}/storage/v1/object/{self._bucket}/{storage_path}",
            content=content.encode("utf-8"),
            headers={"Content-Type": content_type},
        )

        if resp.status_code == 400:
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )
        if resp.status_code not in (200, 201):
            return WriteResult(error=f"Failed to write '{file_path}' (HTTP {resp.status_code})")

        return WriteResult(path=file_path, files_update=None)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Read-modify-write: download, apply replacement, re-upload with upsert."""
        storage_path = self._storage_path(file_path)
        resp = await self._download_raw(storage_path)

        if resp.status_code in (400, 404):
            return EditResult(error=f"Error: File '{file_path}' not found")
        if resp.status_code != 200:
            return EditResult(error=f"Error: Failed to read '{file_path}' (HTTP {resp.status_code})")

        try:
            content = resp.content.decode("utf-8")
        except UnicodeDecodeError:
            return EditResult(error=f"Error: File '{file_path}' is not a text file")

        result = perform_string_replacement(content, old_string, new_string, replace_all)
        if isinstance(result, str):
            return EditResult(error=result)

        new_content, occurrences = result

        client = await self._get_client()
        content_type = self._content_type(file_path)
        put_resp = await client.put(
            f"{self._base_url}/storage/v1/object/{self._bucket}/{storage_path}",
            content=new_content.encode("utf-8"),
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )
        if put_resp.status_code not in (200, 201):
            return EditResult(error=f"Error: Failed to save edit to '{file_path}' (HTTP {put_resp.status_code})")

        return EditResult(path=file_path, files_update=None, occurrences=int(occurrences))

    async def agrep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search stored files for a text pattern."""
        prefix = self._storage_prefix(path or "/")
        items = await self._list_objects(prefix, recursive=True)

        sem = asyncio.Semaphore(_DOWNLOAD_SEMAPHORE_LIMIT)
        files: dict[str, Any] = {}

        async def _download_text(item: dict[str, Any]) -> None:
            name = item.get("name", "")
            full_prefix = item.get("_full_prefix", prefix)
            full_path = f"{full_prefix}{name}"
            virtual = self._to_virtual(full_path)

            if _get_file_type(virtual) != "text":
                return

            async with sem:
                resp = await self._download_raw(full_path)
                if resp.status_code == 200:
                    try:
                        text = resp.content.decode("utf-8")
                    except UnicodeDecodeError:
                        return
                    now = datetime.now(UTC).isoformat()
                    files[virtual] = {
                        "content": text.splitlines(),
                        "encoding": "utf-8",
                        "created_at": now,
                        "modified_at": item.get("updated_at", now),
                    }

        await asyncio.gather(*[_download_text(item) for item in items])
        return grep_matches_from_files(files, pattern, path, glob)

    async def aglob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern."""
        prefix = self._storage_prefix(path)
        items = await self._list_objects(prefix, recursive=True)

        files: dict[str, Any] = {}
        for item in items:
            name = item.get("name", "")
            full_prefix = item.get("_full_prefix", prefix)
            full_path = f"{full_prefix}{name}"
            virtual = self._to_virtual(full_path)
            metadata = item.get("metadata") or {}
            files[virtual] = {
                "content": "",
                "encoding": "utf-8",
                "created_at": item.get("created_at", ""),
                "modified_at": item.get("updated_at", ""),
                "size": metadata.get("size", 0),
            }

        result = _glob_search_files(files, pattern, path)
        if result == "No files found":
            return []

        paths = result.split("\n")
        infos: list[FileInfo] = []
        for p in paths:
            fd = files.get(p)
            infos.append(
                FileInfo(
                    path=p,
                    is_dir=False,
                    size=fd.get("size", 0) if fd else 0,
                    modified_at=fd.get("modified_at", "") if fd else "",
                )
            )
        return infos

    async def aupload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files with upsert semantics."""
        client = await self._get_client()
        responses: list[FileUploadResponse] = []

        for path, content in files:
            storage_path = self._storage_path(path)
            content_type = self._content_type(path)

            resp = await client.post(
                f"{self._base_url}/storage/v1/object/{self._bucket}/{storage_path}",
                content=content,
                headers={"Content-Type": content_type, "x-upsert": "true"},
            )

            if resp.status_code in (200, 201):
                responses.append(FileUploadResponse(path=path, error=None))
            elif resp.status_code == 403:
                responses.append(FileUploadResponse(path=path, error="permission_denied"))
            else:
                responses.append(FileUploadResponse(path=path, error="invalid_path"))

        return responses

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files in parallel."""
        sem = asyncio.Semaphore(_DOWNLOAD_SEMAPHORE_LIMIT)

        async def _download(path: str) -> FileDownloadResponse:
            storage_path = self._storage_path(path)
            async with sem:
                resp = await self._download_raw(storage_path)
            if resp.status_code in (400, 404):
                return FileDownloadResponse(path=path, content=None, error="file_not_found")
            if resp.status_code != 200:
                return FileDownloadResponse(path=path, content=None, error="permission_denied")
            return FileDownloadResponse(path=path, content=resp.content, error=None)

        results = await asyncio.gather(*[_download(p) for p in paths])
        return list(results)

    # ------------------------------------------------------------------
    # Sync protocol methods — not supported (Park is async-only)
    # ------------------------------------------------------------------

    def ls_info(self, path: str) -> list[FileInfo]:
        raise _not_implemented("ls_info")

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        raise _not_implemented("read")

    def write(self, file_path: str, content: str) -> WriteResult:
        raise _not_implemented("write")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        raise _not_implemented("edit")

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        raise _not_implemented("grep_raw")

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        raise _not_implemented("glob_info")

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        raise _not_implemented("upload_files")

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        raise _not_implemented("download_files")
