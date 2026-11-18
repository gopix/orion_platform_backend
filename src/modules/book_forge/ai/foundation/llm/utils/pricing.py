"""Cost estimation for LLM calls.

Prices are USD per 1,000,000 tokens as ``(input_rate, output_rate)``.

NOTE: these are approximate placeholders and change over time — verify against
the provider's current pricing and update / override as needed. Unknown models
return ``None`` (cost is simply logged as "n/a").
"""
from typing import Dict, Optional, Tuple

from src.modules.book_forge.ai.foundation.llm.models import LLMUsage

# model id -> (input $/1M, output $/1M). APPROXIMATE — verify before relying on.
MODEL_PRICING: Dict[str, Tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
}


def compute_cost(model: str, usage: LLMUsage) -> Optional[float]:
    """Estimate the USD cost of a call, or ``None`` if the model is unpriced."""
    rates = MODEL_PRICING.get(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    return (usage.input_tokens / 1_000_000) * input_rate + (
        usage.output_tokens / 1_000_000
    ) * output_rate


def register_pricing(model: str, input_rate: float, output_rate: float) -> None:
    """Register or override pricing for a model (USD per 1M tokens)."""
    MODEL_PRICING[model] = (input_rate, output_rate)
