"""TokenEstimator — estimate (never exactly count) the tokens in a piece of text.

Every strategy needs a cheap, dependency-free answer to "is this chunk getting
too large?", and later the same estimate feeds embedding batching, LLM context
budgeting, and cost estimation. It is deliberately approximate: a real tokenizer
is model-specific and heavyweight, whereas this is a pure function usable
anywhere.

The heuristic is ~4 characters per token, the same ratio every strategy already
assumed — keeping estimates consistent across the whole module. Stateless and
pure: no I/O, no model, no configuration.
"""
import math

# Average characters per token for English-ish text. Approximate by design.
CHARS_PER_TOKEN = 4


class TokenEstimator:
    """Rough token counting via a fixed characters-per-token ratio."""

    @staticmethod
    def estimate(text: str) -> int:
        """Estimate the number of tokens in ``text``.

        Empty or whitespace-only text is 0 tokens; any real content is at least
        one token.
        """
        if not text or not text.strip():
            return 0
        return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))

    @staticmethod
    def fits(text: str, max_tokens: int) -> bool:
        """True if ``text`` is estimated to fit within ``max_tokens``."""
        return TokenEstimator.estimate(text) <= max_tokens
