"""Test importing files."""


def test_imports() -> None:
    """Test importing embient modules."""
    from embient import (
        agent,  # noqa: F401
        integrations,  # noqa: F401
    )
    from embient.main import cli_main  # noqa: F401
