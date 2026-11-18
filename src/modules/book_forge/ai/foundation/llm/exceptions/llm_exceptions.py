"""Exception hierarchy for the LLM layer.

All LLM errors derive from ``LLMException`` so callers can catch the whole
family with a single ``except LLMException``. Providers should translate their
vendor SDK errors into these types so the rest of the application stays
provider-agnostic.
"""
from typing import Optional


class LLMException(Exception):
    """Base class for all LLM-related errors.

    Attributes
    ----------
    message: human-readable description.
    provider: the provider name that raised the error, if known.
    status_code: the upstream HTTP status code, if any.
    original: the underlying exception that was translated, if any.
    """

    def __init__(
        self,
        message: str,
        *,
        provider: Optional[str] = None,
        status_code: Optional[int] = None,
        original: Optional[BaseException] = None,
    ):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.status_code = status_code
        self.original = original

    def __str__(self) -> str:
        parts = [self.message]
        if self.provider:
            parts.append(f"provider={self.provider}")
        if self.status_code is not None:
            parts.append(f"status_code={self.status_code}")
        return " | ".join(parts)


class ProviderException(LLMException):
    """A provider returned an error, or the call to it failed unexpectedly."""


class RateLimitException(LLMException):
    """The provider rejected the request due to rate limiting (HTTP 429)."""


class AuthenticationException(LLMException):
    """The provider rejected the credentials (HTTP 401 / 403)."""
