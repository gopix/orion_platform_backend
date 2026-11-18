"""Enumeration of supported LLM providers.

Use this instead of bare strings when selecting a provider, e.g.::

    llm_service.generate(request, provider=LLMProvider.ANTHROPIC)

Subclassing ``str`` keeps it JSON-friendly and comparable to plain strings,
while still giving callers autocomplete and typo-safety.
"""
from enum import Enum


class LLMProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"
    OLLAMA = "ollama"

    @classmethod
    def coerce(cls, value) -> "LLMProvider":
        """Return an ``LLMProvider`` from an enum member or a string.

        Raises ``ValueError`` with the list of valid options on a bad value.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).lower())
        except ValueError:
            available = ", ".join(member.value for member in cls)
            raise ValueError(
                f"Unknown LLM provider '{value}'. Available providers: {available}."
            )
