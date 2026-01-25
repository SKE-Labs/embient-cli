"""Unit tests for backend utility functions."""

import pytest
from deepanalysts.backends.utils import (
    create_content_preview,
    format_content_with_line_numbers,
    truncate_if_too_long,
)


class TestCreateContentPreview:
    """Tests for the create_content_preview function."""

    def test_small_content_shows_all_lines(self):
        """When content has fewer lines than head + tail, show all lines."""
        content = "line1\nline2\nline3"
        result = create_content_preview(content, head_lines=5, tail_lines=5)
        # Should contain all lines with line numbers
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result
        assert "truncated" not in result

    def test_large_content_shows_head_and_tail(self):
        """When content exceeds head + tail lines, show head, truncation marker, and tail."""
        lines = [f"line{i}" for i in range(1, 101)]  # 100 lines
        content = "\n".join(lines)
        result = create_content_preview(content, head_lines=5, tail_lines=5)

        # Should contain head lines
        assert "line1" in result
        assert "line5" in result

        # Should contain truncation marker
        assert "90 lines truncated" in result

        # Should contain tail lines
        assert "line96" in result
        assert "line100" in result

        # Should NOT contain middle lines
        assert "line50" not in result

    def test_truncation_marker_shows_correct_count(self):
        """The truncation marker should show the correct number of omitted lines."""
        lines = [f"line{i}" for i in range(1, 21)]  # 20 lines
        content = "\n".join(lines)
        result = create_content_preview(content, head_lines=3, tail_lines=3)

        # 20 total - 3 head - 3 tail = 14 truncated
        assert "14 lines truncated" in result

    def test_long_lines_are_truncated(self):
        """Lines longer than 1000 chars should be truncated in the preview."""
        long_line = "x" * 2000
        content = f"short\n{long_line}\nend"
        result = create_content_preview(content)

        # The long line should be capped at 1000 chars
        assert "x" * 1000 in result
        assert "x" * 1001 not in result

    def test_default_head_tail_values(self):
        """Default head_lines and tail_lines should be 5 each."""
        lines = [f"line{i}" for i in range(1, 21)]  # 20 lines
        content = "\n".join(lines)
        result = create_content_preview(content)

        # Should show first 5 and last 5 lines
        assert "line1" in result
        assert "line5" in result
        assert "line16" in result
        assert "line20" in result

        # 20 - 5 - 5 = 10 truncated
        assert "10 lines truncated" in result

    def test_exactly_head_plus_tail_lines(self):
        """Content with exactly head + tail lines should show all (no truncation)."""
        lines = [f"line{i}" for i in range(1, 11)]  # 10 lines
        content = "\n".join(lines)
        result = create_content_preview(content, head_lines=5, tail_lines=5)

        # Should show all lines without truncation
        for i in range(1, 11):
            assert f"line{i}" in result
        assert "truncated" not in result


class TestFormatContentWithLineNumbers:
    """Tests for the format_content_with_line_numbers function."""

    def test_basic_formatting(self):
        """Lines should be prefixed with line numbers."""
        content = "line1\nline2\nline3"
        result = format_content_with_line_numbers(content)
        assert "1\t" in result
        assert "2\t" in result
        assert "3\t" in result

    def test_custom_start_line(self):
        """Line numbers should start from the specified start_line."""
        content = "line1\nline2"
        result = format_content_with_line_numbers(content, start_line=10)
        assert "10\t" in result
        assert "11\t" in result

    def test_list_input(self):
        """Should accept list of strings as input."""
        content = ["line1", "line2", "line3"]
        result = format_content_with_line_numbers(content)
        assert "line1" in result
        assert "line3" in result


class TestTruncateIfTooLong:
    """Tests for the truncate_if_too_long function."""

    def test_short_string_unchanged(self):
        """Short strings should be returned unchanged."""
        result = truncate_if_too_long("short string")
        assert result == "short string"

    def test_short_list_unchanged(self):
        """Short lists should be returned unchanged."""
        items = ["item1", "item2", "item3"]
        result = truncate_if_too_long(items)
        assert result == items

    def test_long_string_truncated(self):
        """Long strings should be truncated with guidance."""
        long_string = "x" * 100000  # Exceeds 20000 * 4 = 80000 chars
        result = truncate_if_too_long(long_string)
        assert len(result) < len(long_string)
        assert "truncated" in result.lower()

    def test_long_list_truncated(self):
        """Long lists should be truncated with guidance."""
        # Each item needs to be long enough to exceed threshold
        # Threshold is 20000 * 4 = 80000 chars total
        items = [f"item{'x' * 100}{i}" for i in range(1000)]  # ~100 chars each = 100000 chars
        result = truncate_if_too_long(items)
        assert len(result) < len(items)
        assert "truncated" in result[-1].lower()
