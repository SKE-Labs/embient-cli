"""Utility functions for middleware."""

from __future__ import annotations

from langchain_core.messages import SystemMessage

# Key used in SystemMessage.additional_kwargs to store section names.
# Parallel to content_blocks: sections[i] names blocks[i].
SECTIONS_KEY = "_prompt_sections"


def _preserve_kwargs(system_message: SystemMessage | None) -> dict:
    """Return a copy of additional_kwargs from a system message, or empty dict."""
    if system_message is None:
        return {}
    return dict(system_message.additional_kwargs)


def append_to_system_message(
    system_message: SystemMessage | None,
    text: str,
) -> SystemMessage:
    """Append text to a system message.

    Handles both string content and content blocks properly by using
    content_blocks API which always returns a list.  Preserves
    ``additional_kwargs`` (including section metadata) from the original
    message.

    Args:
        system_message: Existing system message or None.
        text: Text to add to the system message.

    Returns:
        New SystemMessage with the text appended.
    """
    new_content: list[str | dict[str, str]] = list(system_message.content_blocks) if system_message else []
    if new_content:
        text = f"\n\n{text}"
    new_content.append({"type": "text", "text": text})
    return SystemMessage(content=new_content, additional_kwargs=_preserve_kwargs(system_message))


def insert_after_section(
    system_message: SystemMessage | None,
    text: str,
    section_name: str,
) -> SystemMessage:
    """Insert a content block after a named section.

    Section names are stored in ``additional_kwargs[SECTIONS_KEY]`` as a list
    parallel to the content blocks.  If *section_name* is found, the new text
    is inserted immediately after that block; otherwise the call falls back to
    :func:`append_to_system_message`.

    Args:
        system_message: Existing system message (may carry section metadata).
        text: Text to insert.
        section_name: Name of the section to insert after.

    Returns:
        New SystemMessage with the text inserted at the correct position.
    """
    if system_message is None:
        return append_to_system_message(None, text)

    sections: list[str] = system_message.additional_kwargs.get(SECTIONS_KEY, [])
    if section_name not in sections:
        return append_to_system_message(system_message, text)

    blocks: list[str | dict[str, str]] = list(system_message.content_blocks)
    idx = sections.index(section_name)
    insert_at = idx + 1

    blocks.insert(insert_at, {"type": "text", "text": f"\n\n{text}"})

    new_sections = list(sections)
    new_sections.insert(insert_at, f"_after_{section_name}")

    kwargs = _preserve_kwargs(system_message)
    kwargs[SECTIONS_KEY] = new_sections
    return SystemMessage(content=blocks, additional_kwargs=kwargs)
