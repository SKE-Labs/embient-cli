"""Centralized retry utilities for transient error handling.

Provides retry configuration for:
- External API calls (Basement, etc.)
- Network-related transient errors
"""

import logging

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class RetryableError(Exception):
    """Exception class for errors that should be retried.

    Use this to wrap non-standard errors that should trigger retry logic.
    """

    def __init__(self, message: str, original_error: Exception | None = None):
        super().__init__(message)
        self.original_error = original_error


def is_retryable_exception(exc: BaseException) -> bool:
    """Determine if an exception is retryable (transient).

    Handles:
    - Custom RetryableError (always retryable by design)
    - httpx timeout and connection errors
    - Server errors (5xx status codes)
    - Rate limit errors (429)
    - Google Generative AI errors (ServerError, TooManyRequestsError, TypeError bug)
    """
    # Custom RetryableError is always retryable
    if isinstance(exc, RetryableError):
        return True

    # Network-level errors (always retryable)
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):
        return True

    # HTTP status code errors
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        # 5xx server errors and 429 rate limits are retryable
        if status >= 500 or status == 429:
            return True

    # Handle the google-genai TypeError bug (issue #1897)
    # This occurs when the API returns a 500 error with aiohttp backend
    if isinstance(exc, TypeError):
        error_msg = str(exc)
        if "'ClientResponse' object is not subscriptable" in error_msg:
            logger.warning("Caught google-genai TypeError bug (#1897), retrying...")
            return True

    # Check exception class name for library-specific errors
    exc_type_name = type(exc).__name__

    # Generic server errors from various libraries
    if "ServerError" in exc_type_name or "ConnectionError" in exc_type_name:
        logger.warning(f"Caught {exc_type_name}, retrying: {exc}")
        return True

    # Rate limit errors
    if exc_type_name == "TooManyRequestsError":
        logger.warning(f"Caught rate limit error, retrying: {exc}")
        return True

    return False


def log_retry_attempt(retry_state: RetryCallState) -> None:
    """Log retry attempts for debugging."""
    if retry_state.attempt_number > 1:
        logger.warning(
            f"Retry attempt {retry_state.attempt_number} "
            f"after error: {retry_state.outcome.exception() if retry_state.outcome else 'unknown'}"
        )


def create_async_retry(
    max_attempts: int = 3,
    min_wait: float = 1.0,
    max_wait: float = 8.0,
    multiplier: float = 2.0,
) -> AsyncRetrying:
    """Create an async retry context manager with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts (default: 3)
        min_wait: Minimum wait time in seconds (default: 1.0)
        max_wait: Maximum wait time in seconds (default: 8.0)
        multiplier: Exponential backoff multiplier (default: 2.0)

    Returns:
        AsyncRetrying context manager

    Usage:
        async for attempt in create_async_retry():
            with attempt:
                result = await some_api_call()
    """
    return AsyncRetrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=multiplier, min=min_wait, max=max_wait),
        retry=retry_if_exception(is_retryable_exception),
        before_sleep=log_retry_attempt,
        reraise=True,
    )
