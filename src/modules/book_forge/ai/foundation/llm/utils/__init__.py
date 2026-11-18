"""Utilities for the LLM layer: token counting, model mapping, retries, pricing."""
from src.modules.book_forge.ai.foundation.llm.utils.model_mapping import (
    MODEL_ALIASES,
    provider_for_model,
    register_alias,
    resolve_model,
)
from src.modules.book_forge.ai.foundation.llm.utils.pricing import (
    MODEL_PRICING,
    compute_cost,
    register_pricing,
)
from src.modules.book_forge.ai.foundation.llm.utils.retry import call_with_retry, retry
from src.modules.book_forge.ai.foundation.llm.utils.token_counter import (
    count_message_tokens,
    count_tokens,
)

__all__ = [
    # token counting
    "count_tokens",
    "count_message_tokens",
    # model mapping
    "MODEL_ALIASES",
    "provider_for_model",
    "resolve_model",
    "register_alias",
    # retry
    "retry",
    "call_with_retry",
    # pricing
    "MODEL_PRICING",
    "compute_cost",
    "register_pricing",
]
