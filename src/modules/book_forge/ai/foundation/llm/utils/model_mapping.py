"""Model mapping utilities.

Two jobs:

1. Resolve friendly aliases (e.g. ``"claude-haiku"``) to concrete provider
   model IDs.
2. Infer which provider owns a given model name, so callers can pass just a
   model and let the service route it.

Providers are represented by the ``LLMProvider`` enum, never bare strings.
"""
from typing import Dict, Optional, Tuple, Union

from src.modules.book_forge.ai.foundation.llm.providers.llm_provider import LLMProvider

# Friendly alias -> (provider, concrete model id).
MODEL_ALIASES: Dict[str, Tuple[LLMProvider, str]] = {
    "claude-haiku": (LLMProvider.ANTHROPIC, "claude-haiku-4-5-20251001"),
    "gpt-4o": (LLMProvider.OPENAI, "gpt-4o"),
    "gpt-4o-mini": (LLMProvider.OPENAI, "gpt-4o-mini"),
    "gemini-flash": (LLMProvider.GEMINI, "gemini-1.5-flash"),
    "gemini-pro": (LLMProvider.GEMINI, "gemini-1.5-pro"),
    "llama3": (LLMProvider.OLLAMA, "llama3"),
}

# Model-name prefix -> provider, used when no alias matches.
_PREFIX_PROVIDERS = (
    (("claude",), LLMProvider.ANTHROPIC),
    (("gpt", "o1", "o3", "text-embedding", "davinci"), LLMProvider.OPENAI),
    (("gemini", "models/"), LLMProvider.GEMINI),
)

DEFAULT_PROVIDER = LLMProvider.OLLAMA


def provider_for_model(model: str) -> LLMProvider:
    """Infer the provider that owns ``model`` from its name."""
    name = model.lower()
    for prefixes, provider in _PREFIX_PROVIDERS:
        if name.startswith(prefixes):
            return provider
    return DEFAULT_PROVIDER


def resolve_model(name: str) -> Tuple[LLMProvider, str]:
    """Resolve an alias or raw model name to ``(LLMProvider, model_id)``."""
    if name in MODEL_ALIASES:
        return MODEL_ALIASES[name]
    return provider_for_model(name), name


def register_alias(
    alias: str,
    provider: Union[LLMProvider, str],
    model_id: Optional[str] = None,
) -> None:
    """Register (or override) a friendly alias at runtime."""
    MODEL_ALIASES[alias] = (LLMProvider.coerce(provider), model_id or alias)
