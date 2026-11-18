"""Token counting helpers.

Uses ``tiktoken`` when available for accurate counts; otherwise falls back to a
character-based heuristic so callers always get a usable estimate without a hard
dependency on any tokenizer package.
"""
from typing import Iterable, Optional

from src.modules.book_forge.ai.foundation.llm.models import LLMMessage

# Rough average across English text / common tokenizers.
_APPROX_CHARS_PER_TOKEN = 4
# Approximate per-message structural overhead (role, delimiters).
_PER_MESSAGE_OVERHEAD = 4


def count_tokens(text: str, model: Optional[str] = None) -> int:
    """Return the token count for ``text``, best-effort."""
    if not text:
        return 0

    try:
        import tiktoken

        try:
            encoding = (
                tiktoken.encoding_for_model(model)
                if model
                else tiktoken.get_encoding("cl100k_base")
            )
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # Heuristic fallback (ceil division).
        return max(1, -(-len(text) // _APPROX_CHARS_PER_TOKEN))


def count_message_tokens(
    messages: Iterable[LLMMessage], model: Optional[str] = None
) -> int:
    """Return an approximate token count for a list of chat messages."""
    total = 0
    for message in messages:
        total += count_tokens(message.content, model) + _PER_MESSAGE_OVERHEAD
    return total
