"""tenacity-based retry policy for external API calls."""

from __future__ import annotations

import logging

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)

RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.HTTPStatusError,
)


def _log_retry(state: RetryCallState) -> None:
    fn_name = state.fn.__name__ if state.fn else "?"
    if state.outcome and state.outcome.failed:
        exc = state.outcome.exception()
        logger.warning(
            "retry",
            extra={
                "fn": fn_name,
                "attempt": state.attempt_number,
                "exc_type": type(exc).__name__ if exc else None,
                "exc": str(exc) if exc else None,
            },
        )


retry_api_call = retry(
    retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
    wait=wait_exponential_jitter(initial=0.25, max=4.0, jitter=0.5),
    stop=stop_after_attempt(4),
    before_sleep=_log_retry,
    reraise=True,
)


def async_retrying() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        wait=wait_exponential_jitter(initial=0.25, max=4.0, jitter=0.5),
        stop=stop_after_attempt(4),
        before_sleep=_log_retry,
        reraise=True,
    )
