"""Retry helpers for transient LLM failures.

Provides a ``retry`` decorator and an equivalent ``call_with_retry`` function,
both using exponential backoff with optional jitter. By default they retry only
on the transient LLM error types (rate limits and generic provider errors).
"""
import functools
import random
import time
from typing import Callable, Tuple, Type, TypeVar

from src.core.logger import get_logger
from src.modules.book_forge.ai.foundation.llm.exceptions import (
    ProviderException,
    RateLimitException,
)

logger = get_logger(__name__)

T = TypeVar("T")

# Errors considered worth retrying by default.
DEFAULT_RETRYABLE: Tuple[Type[BaseException], ...] = (
    RateLimitException,
    ProviderException,
)


def _sleep_seconds(delay: float, max_delay: float, jitter: bool) -> float:
    capped = min(delay, max_delay)
    if jitter:
        # Random between 50% and 100% of the capped delay.
        capped *= 0.5 + random.random() / 2
    return capped


def call_with_retry(
    func: Callable[..., T],
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
    jitter: bool = True,
    retry_on: Tuple[Type[BaseException], ...] = DEFAULT_RETRYABLE,
    **kwargs,
) -> T:
    """Call ``func`` with retries on transient errors, using exponential backoff."""
    attempt = 0
    delay = base_delay
    while True:
        try:
            return func(*args, **kwargs)
        except retry_on as exc:
            attempt += 1
            if attempt > max_retries:
                logger.error(
                    "Retries exhausted (%d) for %s: %s",
                    max_retries,
                    getattr(func, "__name__", "call"),
                    exc,
                )
                raise
            sleep = _sleep_seconds(delay, max_delay, jitter)
            logger.warning(
                "Retry %d/%d for %s after error: %s (sleeping %.2fs)",
                attempt,
                max_retries,
                getattr(func, "__name__", "call"),
                exc,
                sleep,
            )
            time.sleep(sleep)
            delay *= backoff


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
    jitter: bool = True,
    retry_on: Tuple[Type[BaseException], ...] = DEFAULT_RETRYABLE,
):
    """Decorator form of :func:`call_with_retry`."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            return call_with_retry(
                func,
                *args,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                backoff=backoff,
                jitter=jitter,
                retry_on=retry_on,
                **kwargs,
            )

        return wrapper

    return decorator
