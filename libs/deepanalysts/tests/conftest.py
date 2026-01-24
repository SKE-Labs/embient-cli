"""Shared pytest fixtures for deepanalysts tests."""

import pytest


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for all async tests."""
    return "asyncio"
