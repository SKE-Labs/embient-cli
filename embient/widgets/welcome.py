"""Welcome banner widget for embient-cli."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from embient._version import __version__
from embient.config import settings

if TYPE_CHECKING:
    from textual.app import ComposeResult

    from embient.trading_config import TradingConfig


class WelcomeBanner(Vertical):
    """Welcome banner displayed at startup with two-column layout."""

    DEFAULT_CSS = """
    WelcomeBanner {
        height: auto;
        border: round #333333;
        border-title-color: #e2e8f0;
        border-title-style: bold;
        padding: 1 2;
        margin: 0 0 1 0;
    }

    WelcomeBanner .welcome-columns {
        height: auto;
    }

    WelcomeBanner .welcome-left {
        width: 1fr;
        height: auto;
        padding-right: 2;
    }

    WelcomeBanner .welcome-right {
        width: 1fr;
        height: auto;
        padding-left: 2;
    }

    WelcomeBanner .welcome-greeting {
        color: white;
        text-style: bold;
        margin-bottom: 1;
    }

    WelcomeBanner .welcome-detail {
        color: $text-muted;
    }

    WelcomeBanner .welcome-context {
        color: $text-muted;
        margin-top: 1;
    }

    WelcomeBanner .welcome-section-title {
        color: #e2e8f0;
        text-style: bold;
        margin-bottom: 1;
    }

    WelcomeBanner .welcome-config-table {
        color: $text-muted;
    }

    WelcomeBanner .welcome-tips-section {
        color: $text-muted;
        margin-top: 1;
    }

    WelcomeBanner .welcome-tip-line {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        model_name: str | None = None,
        agent_info: dict[str, int] | None = None,
        cwd: str | None = None,
        user_email: str | None = None,
        trading_config: TradingConfig | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._model_name = model_name or settings.model_name
        self._agent_info = agent_info or {}
        self._cwd = cwd or str(Path.cwd())
        self._user_email = user_email
        self._trading_config = trading_config
        self.border_title = f"Embient v{__version__}"

    def _format_cwd(self) -> str:
        """Format cwd relative to home directory."""
        home = str(Path.home())
        if self._cwd.startswith(home):
            return "~" + self._cwd[len(home) :]
        return self._cwd

    def _get_greeting(self) -> str:
        """Get greeting from email or fallback."""
        if self._user_email:
            name = self._user_email.split("@")[0]
            return f"Welcome back, {name}!"
        return "Welcome!"

    def _get_context_line(self) -> str | None:
        """Build context line from agent info."""
        agents_md = self._agent_info.get("agents_md_count", 0)
        skills = self._agent_info.get("skills_count", 0)
        parts = []
        if agents_md:
            label = "AGENTS.md" if agents_md == 1 else "AGENTS.md files"
            parts.append(f"{agents_md} {label}")
        if skills:
            label = "skill" if skills == 1 else "skills"
            parts.append(f"{skills} {label}")
        if parts:
            return " | ".join(parts)
        return None

    def compose(self) -> ComposeResult:
        """Compose the two-column welcome layout."""
        with Horizontal(classes="welcome-columns"):
            # Left column
            with Vertical(classes="welcome-left"):
                yield Static(self._get_greeting(), classes="welcome-greeting")

                if self._model_name:
                    yield Static(f"[dim]{self._model_name}[/dim]", classes="welcome-detail")

                yield Static(f"[dim]{self._format_cwd()}[/dim]", classes="welcome-detail")

                # LangSmith status
                langsmith_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY")
                langsmith_tracing = os.environ.get("LANGSMITH_TRACING") or os.environ.get("LANGCHAIN_TRACING_V2")
                if langsmith_key and langsmith_tracing:
                    project = settings.embient_langchain_project or os.environ.get("LANGSMITH_PROJECT") or "default"
                    yield Static(
                        f"[green]\u2713[/green] [dim]LangSmith: '{project}'[/dim]",
                        classes="welcome-detail",
                    )

                context_line = self._get_context_line()
                if context_line:
                    yield Static(f"[dim]{context_line}[/dim]", classes="welcome-context")

            # Right column
            with Vertical(classes="welcome-right"):
                if self._trading_config is not None:
                    yield Static("Trading Configuration", classes="welcome-section-title")

                    symbol = self._trading_config.default_symbol or "[dim]not set[/dim]"
                    config_lines = (
                        f"  Symbol        {symbol}\n"
                        f"  Exchange      {self._trading_config.default_exchange}\n"
                        f"  Interval      {self._trading_config.default_interval}\n"
                        f"  Position      {self._trading_config.default_position_size}%\n"
                        f"  Max Leverage  {self._trading_config.max_leverage}x"
                    )
                    yield Static(config_lines, classes="welcome-config-table")

                yield Static(
                    "[bold]Tips[/bold]" if self._trading_config is None else "\n[bold]Tips[/bold]",
                    classes="welcome-tips-section",
                )
                yield Static(
                    "  [dim]@[/dim] files  [dim]/[/dim] commands  [dim]![/dim] bash\n"
                    "  [dim]Shift+Tab[/dim] auto-approve",
                    classes="welcome-tip-line",
                )
