"""Request context variables for Embient CLI.

Provides context variables for storing session-scoped data
that needs to be accessible from tools and middleware during agent execution.

Usage:
    # At CLI startup (e.g., main.py)
    from embient.context import set_jwt_token, set_thread_id, set_user_profile

    set_jwt_token(jwt_token)
    set_thread_id(thread_id)
    set_user_profile(user_profile)

    # In tools/middleware
    from embient.context import get_jwt_token, get_thread_id, get_user_profile

    jwt_token = get_jwt_token()
"""

from contextvars import ContextVar
from typing import Optional


# JWT token for authenticated API calls
_jwt_token_context: ContextVar[Optional[str]] = ContextVar("jwt_token", default=None)

# Thread ID for conversation tracking
_thread_id_context: ContextVar[Optional[str]] = ContextVar("thread_id", default=None)

# User profile data (account balance, risk settings, etc.)
_user_profile_context: ContextVar[Optional[dict]] = ContextVar("user_profile", default=None)

# Entry plan images for trading signals
_entry_plan_images_context: ContextVar[Optional[list]] = ContextVar(
    "entry_plan_images", default=None
)

# Invalid condition images for trading signals
_invalid_condition_images_context: ContextVar[Optional[list]] = ContextVar(
    "invalid_condition_images", default=None
)

# Screenshots captured via HITL (e.g., chart screenshots from request_chart_screenshot)
_screenshots_context: ContextVar[Optional[list]] = ContextVar("screenshots", default=None)


# JWT Token
def set_jwt_token(token: str) -> None:
    """Set the JWT token for the current session context."""
    _jwt_token_context.set(token)


def get_jwt_token() -> Optional[str]:
    """Get the JWT token from the current session context."""
    return _jwt_token_context.get()


# Thread ID
def set_thread_id(thread_id: str) -> None:
    """Set the thread ID for the current session context."""
    _thread_id_context.set(thread_id)


def get_thread_id() -> Optional[str]:
    """Get the thread ID from the current session context."""
    return _thread_id_context.get()


# User Profile
def set_user_profile(profile: dict) -> None:
    """Set the user profile for the current session context."""
    _user_profile_context.set(profile)


def get_user_profile() -> Optional[dict]:
    """Get the user profile from the current session context."""
    return _user_profile_context.get()


# Entry Plan Images
def set_entry_plan_images(images: list) -> None:
    """Set the entry plan images for the current session context."""
    _entry_plan_images_context.set(images)


def get_entry_plan_images() -> Optional[list]:
    """Get the entry plan images from the current session context."""
    return _entry_plan_images_context.get()


# Invalid Condition Images
def set_invalid_condition_images(images: list) -> None:
    """Set the invalid condition images for the current session context."""
    _invalid_condition_images_context.set(images)


def get_invalid_condition_images() -> Optional[list]:
    """Get the invalid condition images from the current session context."""
    return _invalid_condition_images_context.get()


# Screenshots (HITL-captured chart screenshots)
def set_screenshots(images: list) -> None:
    """Set the screenshots for the current session context.

    These are typically captured via HITL when the user responds to
    a request_chart_screenshot tool call.
    """
    _screenshots_context.set(images)


def get_screenshots() -> Optional[list]:
    """Get the screenshots from the current session context."""
    return _screenshots_context.get()


__all__ = [
    # Setters (for CLI startup)
    "set_jwt_token",
    "set_thread_id",
    "set_user_profile",
    "set_entry_plan_images",
    "set_invalid_condition_images",
    "set_screenshots",
    # Getters (for tools/middleware)
    "get_jwt_token",
    "get_thread_id",
    "get_user_profile",
    "get_entry_plan_images",
    "get_invalid_condition_images",
    "get_screenshots",
]
