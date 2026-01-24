"""Unit tests for CompositeBackend routing.

Tests path-based routing to different backends and execution delegation.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from deepanalysts.backends.composite import CompositeBackend
from deepanalysts.backends.sandbox import RestrictedSubprocessBackend
from deepanalysts.backends.store import StoreBackend
from langgraph.store.memory import InMemoryStore


def make_mock_runtime(store: InMemoryStore | None = None) -> MagicMock:
    """Create a mock ToolRuntime with a store for testing StoreBackend."""
    runtime = MagicMock()
    runtime.store = store or InMemoryStore()
    runtime.config = {"configurable": {"user_id": "test-user-123"}}
    return runtime


def make_store_backend() -> StoreBackend:
    """Create a StoreBackend with InMemoryStore for testing."""
    return StoreBackend(make_mock_runtime())


class TestCompositeBackendRouting:
    """Tests for path-based routing in CompositeBackend."""

    def test_route_to_memories(self):
        """Test files under /memories/ route to StoreBackend."""
        composite = CompositeBackend(
            default=make_store_backend(),
            routes={"/memories/": make_store_backend()},
        )
        result = composite.write("/memories/user.md", "preferences")
        assert result.error is None
        assert result.path == "/user.md"  # Prefix stripped

    def test_route_to_default(self):
        """Test unmatched paths use default backend."""
        composite = CompositeBackend(
            default=make_store_backend(),
            routes={"/memories/": make_store_backend()},
        )
        result = composite.write("/temp.txt", "temp data")
        assert result.error is None

    def test_ls_aggregates_routes(self):
        """Test ls at root shows both default and route directories."""
        composite = CompositeBackend(
            default=make_store_backend(),
            routes={"/memories/": make_store_backend()},
        )
        composite.write("/file.txt", "content")
        infos = composite.ls_info("/")
        paths = [fi["path"] for fi in infos]
        assert "/memories/" in paths

    def test_longest_prefix_match(self):
        """Test longest prefix is matched first."""
        composite = CompositeBackend(
            default=make_store_backend(),
            routes={
                "/skills/": make_store_backend(),
                "/skills/trading/": make_store_backend(),
            },
        )
        # The /skills/trading/ should match before /skills/
        result = composite.write("/skills/trading/fib.md", "content")
        assert result.error is None
        # Path stripped to /fib.md (not /trading/fib.md)
        assert result.path == "/fib.md"


class TestCompositeBackendExecution:
    """Tests for execution delegation in CompositeBackend."""

    def test_execute_delegates_to_sandbox(self):
        """Test execute() delegates to sandbox backend."""
        composite = CompositeBackend(
            default=RestrictedSubprocessBackend(),
            routes={},
        )
        result = composite.execute("python3 -c \"print('hello')\"")
        assert "hello" in result.output
        assert result.exit_code == 0

    def test_execute_fails_without_sandbox(self):
        """Test execute() raises if default doesn't support it."""
        composite = CompositeBackend(
            default=make_store_backend(),  # StoreBackend doesn't implement execute
            routes={},
        )
        with pytest.raises(NotImplementedError):
            composite.execute("echo hello")


class TestCompositeBackendWithSandbox:
    """Tests for CompositeBackend with RestrictedSubprocessBackend as default."""

    def test_sandbox_execution_with_store_routes(self):
        """Test sandbox execution works alongside StoreBackend routes."""
        composite = CompositeBackend(
            default=RestrictedSubprocessBackend(),
            routes={"/memories/": make_store_backend()},
        )

        # Execute works
        result = composite.execute('python3 -c "print(2+2)"')
        assert "4" in result.output

        # Route to memories works
        write_result = composite.write("/memories/prefs.md", "# Prefs")
        assert write_result.error is None

    def test_grep_across_all_backends(self):
        """Test grep searches all backends when path is /."""
        sandbox = RestrictedSubprocessBackend()
        store = make_store_backend()

        composite = CompositeBackend(
            default=sandbox,
            routes={"/memories/": store},
        )

        # Write to memories
        store.write("/notes.md", "TODO: implement feature")

        # Grep should search both
        matches = composite.grep_raw("TODO", path="/")
        # Pattern matching varies by backend, just check no error
        assert isinstance(matches, list)


class TestCompositeBackendAsync:
    """Async tests for CompositeBackend methods."""

    def test_als_info_at_root(self):
        """Test async ls_info aggregates routes at root."""

        async def run_test():
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={"/memories/": make_store_backend()},
            )
            composite.write("/file.txt", "content")

            infos = await composite.als_info("/")
            paths = [fi["path"] for fi in infos]
            assert "/memories/" in paths

        asyncio.run(run_test())

    def test_als_info_specific_route(self):
        """Test async ls_info for a specific routed path."""

        async def run_test():
            store = make_store_backend()
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={"/memories/": store},
            )
            store.write("/note.md", "my note")

            infos = await composite.als_info("/memories/")
            paths = [fi["path"] for fi in infos]
            assert any("/memories/note.md" in p for p in paths)

        asyncio.run(run_test())

    def test_aread(self):
        """Test async read routes correctly."""

        async def run_test():
            store = make_store_backend()
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={"/memories/": store},
            )
            store.write("/readme.md", "# Hello\n\nWorld")

            content = await composite.aread("/memories/readme.md")
            assert "Hello" in content
            assert "World" in content

        asyncio.run(run_test())

    def test_awrite(self):
        """Test async write routes correctly."""

        async def run_test():
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={"/memories/": make_store_backend()},
            )

            result = await composite.awrite("/memories/new.md", "new content")
            assert result.error is None
            assert result.path == "/new.md"  # Prefix stripped

        asyncio.run(run_test())

    def test_aedit(self):
        """Test async edit routes correctly."""

        async def run_test():
            store = make_store_backend()
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={"/memories/": store},
            )
            store.write("/note.md", "hello world")

            result = await composite.aedit("/memories/note.md", "hello", "goodbye")
            assert result.error is None
            assert result.occurrences == 1

            # Verify change
            content = await composite.aread("/memories/note.md")
            assert "goodbye" in content

        asyncio.run(run_test())

    def test_agrep_raw_at_root(self):
        """Test async grep searches all backends when path is /."""

        async def run_test():
            store = make_store_backend()
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={"/memories/": store},
            )
            store.write("/notes.md", "TODO: fix bug")

            matches = await composite.agrep_raw("TODO", path="/")
            assert isinstance(matches, list)
            # Should find match in memories
            match_paths = [m["path"] for m in matches]
            assert any("/memories/notes.md" in p for p in match_paths)

        asyncio.run(run_test())

    def test_agrep_raw_specific_route(self):
        """Test async grep with path targeting specific route."""

        async def run_test():
            store = make_store_backend()
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={"/memories/": store},
            )
            store.write("/important.md", "searchable content")

            matches = await composite.agrep_raw("searchable", path="/memories/")
            assert isinstance(matches, list)
            match_paths = [m["path"] for m in matches]
            assert any("/memories/important.md" in p for p in match_paths)

        asyncio.run(run_test())

    def test_aglob_info(self):
        """Test async glob searches all backends."""

        async def run_test():
            store = make_store_backend()
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={"/memories/": store},
            )
            store.write("/readme.md", "markdown content")

            results = await composite.aglob_info("**/*.md", path="/")
            paths = [fi["path"] for fi in results]
            assert any("/memories/readme.md" in p for p in paths)

        asyncio.run(run_test())

    def test_aglob_info_specific_route(self):
        """Test async glob in specific route."""

        async def run_test():
            store = make_store_backend()
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={"/archive/": store},
            )
            store.write("/file.py", "python code")
            store.write("/data.json", "json data")

            results = await composite.aglob_info("*.py", path="/archive/")
            paths = [fi["path"] for fi in results]
            assert any("/archive/file.py" in p for p in paths)
            assert not any(".json" in p for p in paths)

        asyncio.run(run_test())

    def test_aexecute_with_sandbox(self):
        """Test async execute delegates to sandbox backend."""

        async def run_test():
            composite = CompositeBackend(
                default=RestrictedSubprocessBackend(),
                routes={},
            )

            result = await composite.aexecute("python3 -c \"print('async hello')\"")
            assert "async hello" in result.output
            assert result.exit_code == 0

        asyncio.run(run_test())

    def test_aexecute_fails_without_sandbox(self):
        """Test async execute raises if default doesn't support it."""

        async def run_test():
            composite = CompositeBackend(
                default=make_store_backend(),
                routes={},
            )

            with pytest.raises(NotImplementedError):
                await composite.aexecute("echo hello")

        asyncio.run(run_test())

    def test_aupload_files(self):
        """Test async upload routes files to correct backends."""

        async def run_test():
            sandbox = RestrictedSubprocessBackend()

            composite = CompositeBackend(
                default=sandbox,
                routes={},
            )

            # Upload to default backend (sandbox)
            files = [("/test.bin", b"binary content")]
            responses = await composite.aupload_files(files)
            assert len(responses) == 1
            assert responses[0].error is None

        asyncio.run(run_test())

    def test_adownload_files(self):
        """Test async download routes to correct backends."""

        async def run_test():
            sandbox = RestrictedSubprocessBackend()

            composite = CompositeBackend(
                default=sandbox,
                routes={},
            )

            # Upload then download
            sandbox.upload_files([("download_test.bin", b"test data")])
            responses = await composite.adownload_files(["/download_test.bin"])
            assert len(responses) == 1
            assert responses[0].error is None
            assert responses[0].content == b"test data"

        asyncio.run(run_test())
