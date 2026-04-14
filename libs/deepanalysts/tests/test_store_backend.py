"""Unit tests for StoreBackend improvements.

Tests binary file handling (base64), native async methods, and v1/v2 format support.
"""

import asyncio
import base64
from unittest.mock import MagicMock

import pytest
from deepanalysts.backends.store import StoreBackend
from langgraph.store.memory import InMemoryStore


def make_mock_runtime(store: InMemoryStore | None = None) -> MagicMock:
    runtime = MagicMock()
    runtime.store = store or InMemoryStore()
    runtime.config = {"configurable": {"user_id": "test-user"}}
    return runtime


def make_backend(store: InMemoryStore | None = None) -> StoreBackend:
    s = store or InMemoryStore()
    return StoreBackend(make_mock_runtime(s))


# ---------------------------------------------------------------------------
# Binary file handling (upload/download)
# ---------------------------------------------------------------------------


class TestBinaryUploadDownload:
    def test_upload_text_file(self):
        b = make_backend()
        responses = b.upload_files([("/readme.md", b"# Hello")])
        assert len(responses) == 1
        assert responses[0].error is None

        dl = b.download_files(["/readme.md"])
        assert dl[0].content == b"# Hello"

    def test_upload_binary_file(self):
        """Binary content is auto-detected and stored as base64."""
        b = make_backend()
        binary = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
        responses = b.upload_files([("/image.png", binary)])
        assert responses[0].error is None

        dl = b.download_files(["/image.png"])
        assert dl[0].error is None
        assert dl[0].content == binary

    def test_download_missing_file(self):
        b = make_backend()
        dl = b.download_files(["/nonexistent.md"])
        assert dl[0].error == "file_not_found"
        assert dl[0].content is None


class TestBinaryAsyncUploadDownload:
    def test_async_upload_text(self):
        async def run():
            b = make_backend()
            responses = await b.aupload_files([("/notes.md", b"some text")])
            assert responses[0].error is None
            dl = await b.adownload_files(["/notes.md"])
            assert dl[0].content == b"some text"

        asyncio.run(run())

    def test_async_upload_binary(self):
        async def run():
            b = make_backend()
            binary = bytes(range(256)) * 4
            responses = await b.aupload_files([("/data.bin", binary)])
            assert responses[0].error is None
            dl = await b.adownload_files(["/data.bin"])
            assert dl[0].content == binary

        asyncio.run(run())


# ---------------------------------------------------------------------------
# v1/v2 format converter
# ---------------------------------------------------------------------------


class TestFormatConverter:
    def test_v1_list_content(self):
        """v1 format: content is list[str]."""
        store = InMemoryStore()
        b = make_backend(store)
        # Manually write v1 format
        ns = b._get_namespace()
        store.put(
            ns,
            "/v1file.md",
            {
                "content": ["line1", "line2"],
                "created_at": "2024-01-01",
                "modified_at": "2024-01-01",
            },
        )
        content = b.read("/v1file.md")
        assert "line1" in content
        assert "line2" in content

    def test_v2_str_content_with_encoding(self):
        """v2 format: content is str with encoding field."""
        store = InMemoryStore()
        b = make_backend(store)
        ns = b._get_namespace()
        store.put(
            ns,
            "/v2file.md",
            {
                "content": "hello world",
                "encoding": "utf-8",
                "created_at": "2024-01-01",
                "modified_at": "2024-01-01",
            },
        )
        content = b.read("/v2file.md")
        assert "hello world" in content

    def test_v2_base64_content(self):
        """v2 format with base64 encoding for binary."""
        store = InMemoryStore()
        b = make_backend(store)
        ns = b._get_namespace()
        raw = b"\x89PNG" + b"\x00" * 10
        b64 = base64.standard_b64encode(raw).decode("ascii")
        store.put(
            ns,
            "/binary.png",
            {
                "content": b64,
                "encoding": "base64",
                "created_at": "2024-01-01",
                "modified_at": "2024-01-01",
            },
        )
        dl = b.download_files(["/binary.png"])
        assert dl[0].content == raw

    def test_converter_preserves_encoding(self):
        """_convert_file_data_to_store_value preserves encoding field."""
        b = make_backend()
        file_data = {
            "content": "encoded",
            "encoding": "base64",
            "created_at": "2024-01-01",
            "modified_at": "2024-01-01",
        }
        store_value = b._convert_file_data_to_store_value(file_data)
        assert store_value["encoding"] == "base64"

    def test_converter_omits_encoding_for_v1(self):
        """_convert_file_data_to_store_value omits encoding for v1."""
        b = make_backend()
        file_data = {
            "content": ["line1"],
            "created_at": "2024-01-01",
            "modified_at": "2024-01-01",
        }
        store_value = b._convert_file_data_to_store_value(file_data)
        assert "encoding" not in store_value


# ---------------------------------------------------------------------------
# Native async methods
# ---------------------------------------------------------------------------


class TestNativeAsync:
    def test_aread(self):
        async def run():
            b = make_backend()
            b.write("/doc.md", "async content")
            result = await b.aread("/doc.md")
            assert "async content" in result

        asyncio.run(run())

    def test_aread_not_found(self):
        async def run():
            b = make_backend()
            result = await b.aread("/missing.md")
            assert "not found" in result

        asyncio.run(run())

    def test_awrite(self):
        async def run():
            b = make_backend()
            result = await b.awrite("/new.md", "new content")
            assert result.error is None
            content = b.read("/new.md")
            assert "new content" in content

        asyncio.run(run())

    def test_awrite_existing_errors(self):
        async def run():
            b = make_backend()
            b.write("/existing.md", "old")
            result = await b.awrite("/existing.md", "new")
            assert result.error is not None
            assert "already exists" in result.error

        asyncio.run(run())

    def test_aedit(self):
        async def run():
            b = make_backend()
            b.write("/editable.md", "hello world")
            result = await b.aedit("/editable.md", "hello", "goodbye")
            assert result.error is None
            assert result.occurrences == 1
            content = b.read("/editable.md")
            assert "goodbye world" in content

        asyncio.run(run())

    def test_als_info(self):
        async def run():
            b = make_backend()
            b.write("/dir/file1.md", "f1")
            b.write("/dir/file2.md", "f2")
            b.write("/other.md", "other")

            infos = await b.als_info("/dir/")
            paths = [fi["path"] for fi in infos]
            assert "/dir/file1.md" in paths
            assert "/dir/file2.md" in paths
            assert "/other.md" not in paths

        asyncio.run(run())

    def test_als_info_shows_subdirs(self):
        async def run():
            b = make_backend()
            b.write("/root/sub/file.md", "content")

            infos = await b.als_info("/root/")
            paths = [fi["path"] for fi in infos]
            assert "/root/sub/" in paths

        asyncio.run(run())

    def test_agrep_raw(self):
        async def run():
            b = make_backend()
            b.write("/search.md", "TODO fix this\nok line\nTODO also this")

            matches = await b.agrep_raw("TODO")
            assert isinstance(matches, list)
            assert len(matches) == 2
            assert all(m["path"] == "/search.md" for m in matches)

        asyncio.run(run())

    def test_agrep_raw_no_match(self):
        async def run():
            b = make_backend()
            b.write("/clean.md", "all good here")

            matches = await b.agrep_raw("MISSING")
            assert isinstance(matches, list)
            assert len(matches) == 0

        asyncio.run(run())

    def test_aglob_info(self):
        async def run():
            b = make_backend()
            b.write("/src/main.py", "python code")
            b.write("/src/data.json", "json data")
            b.write("/readme.md", "docs")

            infos = await b.aglob_info("**/*.py")
            paths = [fi["path"] for fi in infos]
            assert "/src/main.py" in paths
            assert "/src/data.json" not in paths

        asyncio.run(run())

    def test_aupload_and_adownload(self):
        async def run():
            b = make_backend()
            await b.aupload_files([("/uploaded.md", b"uploaded content")])
            dl = await b.adownload_files(["/uploaded.md"])
            assert dl[0].content == b"uploaded content"

        asyncio.run(run())
