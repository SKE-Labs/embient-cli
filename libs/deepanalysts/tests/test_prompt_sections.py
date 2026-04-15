"""Tests for section-aware system message utilities.

Tests append_to_system_message (preserves additional_kwargs), insert_after_section,
and SECTIONS_KEY constant from deepanalysts.middleware._utils.
"""

import pytest
from langchain_core.messages import SystemMessage

from deepanalysts.middleware._utils import (
    SECTIONS_KEY,
    append_to_system_message,
    insert_after_section,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_msg() -> SystemMessage:
    """SystemMessage with no section metadata."""
    return SystemMessage(content="plain text")


@pytest.fixture
def sectioned_msg() -> SystemMessage:
    """SystemMessage with three named sections as content blocks."""
    return SystemMessage(
        content=[
            {"type": "text", "text": "Base prompt"},
            {"type": "text", "text": "Session context"},
            {"type": "text", "text": "User account"},
        ],
        additional_kwargs={
            SECTIONS_KEY: ["base", "session", "user_account"],
        },
    )


# ---------------------------------------------------------------------------
# append_to_system_message
# ---------------------------------------------------------------------------


class TestAppendToSystemMessage:
    def test_append_to_none_creates_message(self):
        msg = append_to_system_message(None, "hello")
        assert len(msg.content_blocks) == 1
        assert msg.content_blocks[0]["text"] == "hello"

    def test_append_adds_block(self, empty_msg: SystemMessage):
        msg = append_to_system_message(empty_msg, "extra")
        assert len(msg.content_blocks) == 2
        assert msg.content_blocks[1]["text"] == "\n\nextra"

    def test_preserves_additional_kwargs(self, sectioned_msg: SystemMessage):
        msg = append_to_system_message(sectioned_msg, "appended")
        assert SECTIONS_KEY in msg.additional_kwargs
        assert msg.additional_kwargs[SECTIONS_KEY] == ["base", "session", "user_account"]

    def test_preserves_other_kwargs(self):
        original = SystemMessage(
            content="text",
            additional_kwargs={"custom_key": "custom_value", SECTIONS_KEY: ["a"]},
        )
        msg = append_to_system_message(original, "more")
        assert msg.additional_kwargs["custom_key"] == "custom_value"
        assert msg.additional_kwargs[SECTIONS_KEY] == ["a"]

    def test_does_not_mutate_original(self, sectioned_msg: SystemMessage):
        original_blocks = len(sectioned_msg.content_blocks)
        append_to_system_message(sectioned_msg, "new stuff")
        assert len(sectioned_msg.content_blocks) == original_blocks


# ---------------------------------------------------------------------------
# insert_after_section
# ---------------------------------------------------------------------------


class TestInsertAfterSection:
    def test_inserts_after_named_section(self, sectioned_msg: SystemMessage):
        msg = insert_after_section(sectioned_msg, "Preferences", "user_account")
        blocks = msg.content_blocks
        assert len(blocks) == 4
        # New block should be at index 3 (after user_account at index 2)
        assert "Preferences" in blocks[3]["text"]

    def test_inserts_after_first_section(self, sectioned_msg: SystemMessage):
        msg = insert_after_section(sectioned_msg, "After base", "base")
        blocks = msg.content_blocks
        assert len(blocks) == 4
        assert "After base" in blocks[1]["text"]
        # Original session should shift to index 2
        assert blocks[2]["text"] == "Session context"

    def test_inserts_after_middle_section(self, sectioned_msg: SystemMessage):
        msg = insert_after_section(sectioned_msg, "After session", "session")
        blocks = msg.content_blocks
        assert len(blocks) == 4
        assert "After session" in blocks[2]["text"]
        assert blocks[3]["text"] == "User account"

    def test_updates_section_names(self, sectioned_msg: SystemMessage):
        msg = insert_after_section(sectioned_msg, "Prefs", "user_account")
        sections = msg.additional_kwargs[SECTIONS_KEY]
        assert sections == ["base", "session", "user_account", "_after_user_account"]

    def test_falls_back_to_append_when_section_not_found(self, sectioned_msg: SystemMessage):
        msg = insert_after_section(sectioned_msg, "Fallback", "nonexistent")
        blocks = msg.content_blocks
        assert len(blocks) == 4
        assert "Fallback" in blocks[-1]["text"]

    def test_falls_back_to_append_on_none_message(self):
        msg = insert_after_section(None, "New content", "any_section")
        assert len(msg.content_blocks) == 1
        assert "New content" in msg.content_blocks[0]["text"]

    def test_falls_back_when_no_sections_metadata(self, empty_msg: SystemMessage):
        msg = insert_after_section(empty_msg, "Content", "base")
        # Should append (2 blocks: original + appended)
        assert len(msg.content_blocks) == 2

    def test_preserves_other_kwargs(self):
        original = SystemMessage(
            content=[{"type": "text", "text": "A"}],
            additional_kwargs={
                SECTIONS_KEY: ["a"],
                "custom": "value",
            },
        )
        msg = insert_after_section(original, "B", "a")
        assert msg.additional_kwargs["custom"] == "value"

    def test_does_not_mutate_original(self, sectioned_msg: SystemMessage):
        original_blocks = len(sectioned_msg.content_blocks)
        original_sections = list(sectioned_msg.additional_kwargs[SECTIONS_KEY])
        insert_after_section(sectioned_msg, "New", "base")
        assert len(sectioned_msg.content_blocks) == original_blocks
        assert sectioned_msg.additional_kwargs[SECTIONS_KEY] == original_sections

    def test_multiple_inserts_chain_correctly(self, sectioned_msg: SystemMessage):
        """Two sequential inserts should both land in the right place."""
        msg = insert_after_section(sectioned_msg, "After account", "user_account")
        msg = insert_after_section(msg, "After session", "session")
        sections = msg.additional_kwargs[SECTIONS_KEY]
        assert sections == [
            "base",
            "session",
            "_after_session",
            "user_account",
            "_after_user_account",
        ]
        assert len(msg.content_blocks) == 5

    def test_prepends_newlines_to_inserted_text(self, sectioned_msg: SystemMessage):
        msg = insert_after_section(sectioned_msg, "Content", "base")
        inserted = msg.content_blocks[1]["text"]
        assert inserted.startswith("\n\n")


# ---------------------------------------------------------------------------
# SECTIONS_KEY constant
# ---------------------------------------------------------------------------


class TestSectionsKey:
    def test_key_is_string(self):
        assert isinstance(SECTIONS_KEY, str)

    def test_key_starts_with_underscore(self):
        """Convention: private metadata keys start with underscore."""
        assert SECTIONS_KEY.startswith("_")
