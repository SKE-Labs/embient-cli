"""Unit tests for SupabaseStorageBackend.

Tests all BackendProtocol methods with mocked httpx responses.
"""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from deepanalysts.backends.supabase_storage import SupabaseStorageBackend


def make_backend(**kwargs) -> SupabaseStorageBackend:
    defaults = dict(
        supabase_url="https://test.supabase.co",
        supabase_key="service-role-key",
        bucket="user-files",
        user_id="user-123",
        path_prefix="skills",
    )
    defaults.update(kwargs)
    return SupabaseStorageBackend(**defaults)


def mock_response(status_code: int = 200, content: bytes = b"", json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.json = MagicMock(return_value=json_data or [])
    return resp


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


class TestPathResolution:
    def test_storage_path_with_prefix(self):
        b = make_backend(path_prefix="skills")
        assert b._storage_path("/trend/SKILL.md") == "user-123/skills/trend/SKILL.md"

    def test_storage_path_without_prefix(self):
        b = make_backend(path_prefix="")
        assert b._storage_path("/file.md") == "user-123/file.md"

    def test_storage_path_root(self):
        b = make_backend(path_prefix="memories")
        assert b._storage_path("/") == "user-123/memories"

    def test_storage_prefix(self):
        b = make_backend(path_prefix="skills")
        assert b._storage_prefix("/trend") == "user-123/skills/trend/"
        assert b._storage_prefix("/trend/") == "user-123/skills/trend/"

    def test_to_virtual(self):
        b = make_backend(path_prefix="skills")
        assert b._to_virtual("user-123/skills/trend/SKILL.md") == "/trend/SKILL.md"

    def test_to_virtual_fallback(self):
        b = make_backend(path_prefix="skills")
        assert b._to_virtual("other/path/file.md") == "/file.md"

    def test_user_id_factory(self):
        b = make_backend(user_id=None, user_id_factory=lambda: "dynamic-user")
        assert b._storage_path("/file.md") == "dynamic-user/skills/file.md"

    def test_missing_user_id_raises_on_use(self):
        """No user_id or factory — init succeeds but _get_uid raises at operation time."""
        b = SupabaseStorageBackend(
            supabase_url="https://x.supabase.co",
            supabase_key="key",
        )
        with pytest.raises(ValueError, match="user_id is not available"):
            b._get_uid()

    def test_empty_user_id_factory_raises_on_use(self):
        """Factory returns empty string — _get_uid raises."""
        b = make_backend(user_id=None, user_id_factory=lambda: "")
        with pytest.raises(ValueError, match="user_id is not available"):
            b._get_uid()


# ---------------------------------------------------------------------------
# Async protocol methods
# ---------------------------------------------------------------------------


class TestAread:
    def test_read_text_file(self):
        async def run():
            b = make_backend()
            resp = mock_response(200, b"line1\nline2\nline3")
            with patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=resp):
                result = await b.aread("/file.md")
                assert "line1" in result
                assert "line2" in result

        asyncio.run(run())

    def test_read_not_found(self):
        async def run():
            b = make_backend()
            resp = mock_response(404)
            with patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=resp):
                result = await b.aread("/missing.md")
                assert "not found" in result

        asyncio.run(run())

    def test_read_binary_file(self):
        async def run():
            b = make_backend()
            raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
            resp = mock_response(200, raw)
            with patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=resp):
                result = await b.aread("/image.png")
                # Binary files get base64-encoded and formatted
                assert isinstance(result, str)

        asyncio.run(run())


class TestAwrite:
    def test_write_new_file(self):
        async def run():
            b = make_backend()
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_response(200))
            with patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client):
                result = await b.awrite("/new.md", "content")
                assert result.error is None
                assert result.path == "/new.md"

        asyncio.run(run())

    def test_write_existing_file_errors(self):
        async def run():
            b = make_backend()
            client = AsyncMock()
            # Supabase returns 400 for existing file
            client.post = AsyncMock(return_value=mock_response(400))
            with patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client):
                result = await b.awrite("/existing.md", "content")
                assert result.error is not None
                assert "already exists" in result.error

        asyncio.run(run())


class TestAedit:
    def test_edit_replaces_string(self):
        async def run():
            b = make_backend()
            download_resp = mock_response(200, b"hello world")
            client = AsyncMock()
            client.put = AsyncMock(return_value=mock_response(200))
            with (
                patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=download_resp),
                patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client),
            ):
                result = await b.aedit("/file.md", "hello", "goodbye")
                assert result.error is None
                assert result.occurrences == 1
                # Verify upsert was called
                client.put.assert_called_once()

        asyncio.run(run())

    def test_edit_not_found(self):
        async def run():
            b = make_backend()
            resp = mock_response(404)
            with patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=resp):
                result = await b.aedit("/missing.md", "old", "new")
                assert result.error is not None
                assert "not found" in result.error

        asyncio.run(run())


class TestAuploadFiles:
    def test_upload_with_upsert(self):
        async def run():
            b = make_backend()
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_response(200))
            with patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client):
                responses = await b.aupload_files([("/file.md", b"content")])
                assert len(responses) == 1
                assert responses[0].error is None
                # Verify x-upsert header
                call_kwargs = client.post.call_args
                assert call_kwargs.kwargs.get("headers", {}).get("x-upsert") == "true"

        asyncio.run(run())

    def test_upload_permission_denied(self):
        async def run():
            b = make_backend()
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_response(403))
            with patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client):
                responses = await b.aupload_files([("/file.md", b"content")])
                assert responses[0].error == "permission_denied"

        asyncio.run(run())


class TestAdownloadFiles:
    def test_download_existing_file(self):
        async def run():
            b = make_backend()
            resp = mock_response(200, b"file content")
            with patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=resp):
                responses = await b.adownload_files(["/file.md"])
                assert len(responses) == 1
                assert responses[0].content == b"file content"
                assert responses[0].error is None

        asyncio.run(run())

    def test_download_missing_file(self):
        async def run():
            b = make_backend()
            resp = mock_response(404)
            with patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=resp):
                responses = await b.adownload_files(["/missing.md"])
                assert responses[0].error == "file_not_found"
                assert responses[0].content is None

        asyncio.run(run())


class TestAlsInfo:
    def test_list_directory(self):
        async def run():
            b = make_backend()
            items = [
                {"name": "file.md", "id": "abc", "metadata": {"size": 100}, "updated_at": "2024-01-01"},
                {"name": "subdir", "id": None},  # folder
            ]
            with patch.object(b, "_list_objects", new_callable=AsyncMock, return_value=items):
                infos = await b.als_info("/")
                paths = [fi["path"] for fi in infos]
                assert "/file.md" in paths
                assert "/subdir/" in paths
                # Verify folder is_dir flag
                subdir = next(fi for fi in infos if "subdir" in fi["path"])
                assert subdir["is_dir"] is True

        asyncio.run(run())


class TestAgrepRaw:
    def test_grep_finds_matches(self):
        async def run():
            b = make_backend()
            items = [
                {"name": "file.md", "id": "abc", "_full_prefix": "user-123/skills/", "updated_at": "2024-01-01"},
            ]
            download_resp = mock_response(200, b"line1 TODO fix\nline2 ok\nline3 TODO review")
            with (
                patch.object(b, "_list_objects", new_callable=AsyncMock, return_value=items),
                patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=download_resp),
            ):
                result = await b.agrep_raw("TODO")
                assert isinstance(result, list)
                assert len(result) == 2
                assert result[0]["text"] == "line1 TODO fix"

        asyncio.run(run())


class TestAglobInfo:
    def test_glob_matches_pattern(self):
        async def run():
            b = make_backend()
            items = [
                {
                    "name": "readme.md",
                    "id": "a",
                    "_full_prefix": "user-123/skills/",
                    "metadata": {"size": 50},
                    "updated_at": "2024-01-01",
                    "created_at": "2024-01-01",
                },
                {
                    "name": "data.json",
                    "id": "b",
                    "_full_prefix": "user-123/skills/",
                    "metadata": {"size": 30},
                    "updated_at": "2024-01-01",
                    "created_at": "2024-01-01",
                },
            ]
            with patch.object(b, "_list_objects", new_callable=AsyncMock, return_value=items):
                infos = await b.aglob_info("*.md")
                paths = [fi["path"] for fi in infos]
                assert "/readme.md" in paths
                assert "/data.json" not in paths

        asyncio.run(run())


# ---------------------------------------------------------------------------
# Edge cases and robustness
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_aedit_replace_all(self):
        """aedit with replace_all=True replaces all occurrences."""

        async def run():
            b = make_backend()
            download_resp = mock_response(200, b"foo bar foo baz foo")
            client = AsyncMock()
            client.put = AsyncMock(return_value=mock_response(200))
            with (
                patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=download_resp),
                patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client),
            ):
                result = await b.aedit("/file.md", "foo", "qux", replace_all=True)
                assert result.error is None
                assert result.occurrences == 3
                # Verify content sent to PUT
                put_content = client.put.call_args.kwargs["content"]
                assert put_content == b"qux bar qux baz qux"

        asyncio.run(run())

    def test_aread_server_error(self):
        """HTTP 500 returns a descriptive error, not crash."""

        async def run():
            b = make_backend()
            resp = mock_response(500)
            with patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=resp):
                result = await b.aread("/file.md")
                assert "500" in result
                assert "Error" in result

        asyncio.run(run())

    def test_agrep_no_matches(self):
        """agrep returns empty list when nothing matches."""

        async def run():
            b = make_backend()
            items = [
                {"name": "clean.md", "id": "a", "_full_prefix": "user-123/skills/", "updated_at": "2024-01-01"},
            ]
            download_resp = mock_response(200, b"all good here\nno issues")
            with (
                patch.object(b, "_list_objects", new_callable=AsyncMock, return_value=items),
                patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=download_resp),
            ):
                result = await b.agrep_raw("NONEXISTENT")
                assert isinstance(result, list)
                assert len(result) == 0

        asyncio.run(run())

    def test_agrep_skips_binary_files(self):
        """agrep should skip binary files (images) — only search text."""

        async def run():
            b = make_backend()
            items = [
                {"name": "image.png", "id": "a", "_full_prefix": "user-123/skills/", "updated_at": "2024-01-01"},
                {"name": "readme.md", "id": "b", "_full_prefix": "user-123/skills/", "updated_at": "2024-01-01"},
            ]
            # Only the .md file should be downloaded
            download_resp = mock_response(200, b"search target here")
            with (
                patch.object(b, "_list_objects", new_callable=AsyncMock, return_value=items),
                patch.object(b, "_download_raw", new_callable=AsyncMock, return_value=download_resp),
            ):
                result = await b.agrep_raw("target")
                assert isinstance(result, list)
                assert len(result) == 1
                assert result[0]["path"] == "/readme.md"

        asyncio.run(run())

    def test_awrite_sends_correct_content_type(self):
        """awrite should set Content-Type from file extension."""

        async def run():
            b = make_backend()
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_response(200))
            with patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client):
                await b.awrite("/script.py", "print('hi')")
                call_headers = client.post.call_args.kwargs.get("headers", {})
                ct = call_headers.get("Content-Type", "")
                assert "python" in ct or "text" in ct

        asyncio.run(run())

    def test_aupload_multiple_files(self):
        """aupload_files handles multiple files, preserving order."""

        async def run():
            b = make_backend()
            client = AsyncMock()
            client.post = AsyncMock(return_value=mock_response(200))
            with patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client):
                responses = await b.aupload_files(
                    [
                        ("/a.md", b"aaa"),
                        ("/b.md", b"bbb"),
                        ("/c.md", b"ccc"),
                    ]
                )
                assert len(responses) == 3
                assert all(r.error is None for r in responses)
                assert client.post.call_count == 3

        asyncio.run(run())

    def test_list_objects_pagination(self):
        """_list_objects should paginate when receiving full pages."""

        async def run():
            from deepanalysts.backends.supabase_storage import _LIST_PAGE_SIZE

            b = make_backend()
            client = AsyncMock()

            # First call returns a full page, second returns partial
            page1 = [{"name": f"file{i}.md", "id": str(i)} for i in range(_LIST_PAGE_SIZE)]
            page2 = [{"name": "last.md", "id": "last"}]

            call_count = 0

            async def mock_post(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return mock_response(200, json_data=page1)
                return mock_response(200, json_data=page2)

            client.post = mock_post
            with patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client):
                items = await b._list_objects("user-123/skills/")
                assert len(items) == _LIST_PAGE_SIZE + 1
                assert call_count == 2

        asyncio.run(run())

    def test_list_objects_recursive_descends_folders(self):
        """_list_objects recursive=True descends into sub-folders."""

        async def run():
            b = make_backend()
            client = AsyncMock()

            # Root listing returns a file and a folder
            root_items = [
                {"name": "root.md", "id": "1"},
                {"name": "subdir", "id": None},  # folder
            ]
            # Subfolder listing returns one file
            sub_items = [
                {"name": "nested.md", "id": "2"},
            ]

            call_count = 0

            async def mock_post(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                body = kwargs.get("json", {})
                prefix = body.get("prefix", "")
                if "subdir" in prefix:
                    return mock_response(200, json_data=sub_items)
                return mock_response(200, json_data=root_items)

            client.post = mock_post
            with patch.object(b, "_get_client", new_callable=AsyncMock, return_value=client):
                items = await b._list_objects("user-123/skills/", recursive=True)
                names = [item["name"] for item in items]
                assert "root.md" in names
                assert "nested.md" in names
                assert len(items) == 2  # Only files, no folder entries

        asyncio.run(run())

    def test_als_info_empty_directory(self):
        """als_info returns empty list for empty directory."""

        async def run():
            b = make_backend()
            with patch.object(b, "_list_objects", new_callable=AsyncMock, return_value=[]):
                infos = await b.als_info("/empty/")
                assert infos == []

        asyncio.run(run())


# ---------------------------------------------------------------------------
# Sync methods raise NotImplementedError
# ---------------------------------------------------------------------------


class TestSyncRaises:
    def test_sync_methods_raise(self):
        b = make_backend()
        with pytest.raises(NotImplementedError):
            b.ls_info("/")
        with pytest.raises(NotImplementedError):
            b.read("/file.md")
        with pytest.raises(NotImplementedError):
            b.write("/file.md", "content")
        with pytest.raises(NotImplementedError):
            b.edit("/file.md", "old", "new")
        with pytest.raises(NotImplementedError):
            b.grep_raw("pattern")
        with pytest.raises(NotImplementedError):
            b.glob_info("*.md")
        with pytest.raises(NotImplementedError):
            b.upload_files([])
        with pytest.raises(NotImplementedError):
            b.download_files([])


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_aclose(self):
        async def run():
            b = make_backend()
            mock_client = AsyncMock()
            mock_client.is_closed = False
            b._client = mock_client
            await b.aclose()
            mock_client.aclose.assert_called_once()
            assert b._client is None

        asyncio.run(run())

    def test_aclose_when_no_client(self):
        async def run():
            b = make_backend()
            # Should not raise
            await b.aclose()

        asyncio.run(run())


# ---------------------------------------------------------------------------
# Content-type detection
# ---------------------------------------------------------------------------


class TestContentType:
    def test_markdown(self):
        b = make_backend()
        assert "markdown" in b._content_type("/file.md")

    def test_python(self):
        b = make_backend()
        ct = b._content_type("/script.py")
        assert "python" in ct or "text" in ct

    def test_png(self):
        b = make_backend()
        assert "image/png" in b._content_type("/image.png")

    def test_unknown_defaults_to_text(self):
        b = make_backend()
        assert "text" in b._content_type("/file.zzqq")
