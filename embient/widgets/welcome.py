"""Welcome banner widget for embient-cli."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.widgets import Static

from embient.config import EMBIENT_ASCII, settings

if TYPE_CHECKING:
    from textual.app import ComposeResult


class WelcomeBanner(Vertical):
    """Welcome banner displayed at startup."""

    DEFAULT_CSS = """
    WelcomeBanner {
        height: auto;
        padding: 1;
        margin-bottom: 1;
    }

    WelcomeBanner .banner-ascii {
        color: white;
        text-style: bold;
    }

    WelcomeBanner .banner-model {
        color: $text-muted;
        margin-top: 1;
    }

    WelcomeBanner .banner-langsmith {
        color: $text-muted;
    }

    WelcomeBanner .banner-tips {
        color: $text-muted;
        margin-top: 1;
    }

    WelcomeBanner .banner-context {
        color: $text-muted;
        margin-top: 1;
    }

    WelcomeBanner .banner-prompt {
        color: white;
        margin-top: 1;
    }

    WelcomeBanner .banner-keys {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        model_name: str | None = None,
        agent_info: dict[str, int] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the welcome banner.

        Args:
            model_name: Name of the active model
            agent_info: Dict with agents_md_count and skills_count
            **kwargs: Additional arguments passed to parent
        """
        super().__init__(**kwargs)
        self._model_name = model_name or settings.model_name
        self._agent_info = agent_info or {}

    def compose(self) -> ComposeResult:
        """Compose the welcome banner layout."""
        yield Static(EMBIENT_ASCII, classes="banner-ascii")

        # Model info
        if self._model_name:
            yield Static(
                f"Responding with [bold]{self._model_name}[/bold]",
                classes="banner-model",
            )

        # LangSmith status
        langsmith_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
        langsmith_tracing = os.environ.get("LANGSMITH_TRACING") or os.environ.get("LANGCHAIN_TRACING_V2")
        if langsmith_key and langsmith_tracing:
            project = settings.embient_langchain_project or os.environ.get("LANGSMITH_PROJECT") or "default"
            yield Static(
                f"[green]\u2713[/green] LangSmith tracing: [cyan]'{project}'[/cyan]",
                classes="banner-langsmith",
            )

        # Tips
        tips_text = (
            "[dim]Tips:[/dim]\n"
            "  1. Use @ to reference files        3. Shift+Tab toggles auto-approve\n"
            "  2. Use /remember to save prefs     4. Use ! for shell commands"
        )
        yield Static(tips_text, classes="banner-tips")

        # Agent context info
        agents_md = self._agent_info.get("agents_md_count", 0)
        skills = self._agent_info.get("skills_count", 0)
        context_parts = []
        if agents_md:
            label = "AGENTS.md file" if agents_md == 1 else "AGENTS.md files"
            context_parts.append(f"{agents_md} {label}")
        if skills:
            label = "skill" if skills == 1 else "skills"
            context_parts.append(f"{skills} {label}")
        if context_parts:
            yield Static(f"Using: {' | '.join(context_parts)}", classes="banner-context")

        yield Static("What would you like to analyze?", classes="banner-prompt")
        yield Static(
            "Enter send | Ctrl+J newline | @ files | / commands",
            classes="banner-keys",
        )
