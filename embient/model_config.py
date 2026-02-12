"""Model configuration and discovery for the CLI."""

from __future__ import annotations

import os
from collections import OrderedDict

# Default models per provider
_MODELS_BY_PROVIDER: dict[str, list[str]] = OrderedDict([
    ("openai", [
        "gpt-5-mini",
        "gpt-5.2",
        "gpt-4.1-mini",
        "o4-mini",
    ]),
    ("anthropic", [
        "claude-sonnet-4-5-20250929",
        "claude-opus-4-6",
        "claude-haiku-4-5-20251001",
    ]),
    ("google", [
        "gemini-3-flash-preview",
        "gemini-2.5-pro-preview-05-06",
    ]),
])

_PROVIDER_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def get_available_models() -> dict[str, list[str]]:
    """Get models grouped by provider.

    Returns:
        OrderedDict mapping provider name to list of model names.
    """
    return dict(_MODELS_BY_PROVIDER)


def has_provider_credentials(provider: str) -> bool | None:
    """Check if a provider has valid credentials.

    Args:
        provider: Provider name (openai, anthropic, google).

    Returns:
        True if key is set, False if not, None if provider is unknown.
    """
    env_var = _PROVIDER_ENV_VARS.get(provider)
    if env_var is None:
        return None
    return bool(os.environ.get(env_var))
