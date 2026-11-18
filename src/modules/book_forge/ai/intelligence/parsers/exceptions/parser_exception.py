"""ParserException — base exception for the parser module.

Same shape as the other module bases (chunking/embeddings/vector store): every
parser error derives from this, so callers can catch the whole family with a
single ``except ParserException``. Providers translate their library errors into
these types so raw vendor exceptions never leak.
"""
from typing import Any, Dict, Optional


class ParserException(Exception):
    """Base class for every error raised by the parser module."""

    default_error_code: str = "PARSE-001"
    default_message: str = "Parser error"

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.message = message or self.default_message
        self.error_code = error_code or self.default_error_code
        self.details = details
        self.cause = cause
        super().__init__(self.message)
        if cause is not None:
            self.__cause__ = cause

    def __str__(self) -> str:
        parts = [f"[{self.error_code}] {self.message}"]
        if self.details:
            rendered = ", ".join(f"{k}={v}" for k, v in self.details.items())
            parts.append(f"({rendered})")
        return " ".join(parts)
