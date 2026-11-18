"""Abstract interface every LLM provider implements.

A provider translates the provider-agnostic ``LLMRequest`` into a specific
vendor SDK call and maps the raw result back into an ``LLMResponse``. Concrete
providers live alongside this file (anthropic, openai, gemini, ollama).
"""
from abc import ABC, abstractmethod
from typing import Dict, Iterator, List, Optional, Tuple

from src.modules.book_forge.ai.foundation.llm.models import LLMRequest, LLMResponse, LLMRole


class BaseLLMProvider(ABC):
    """Common contract for all LLM providers."""

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Run a single, non-streaming completion and return the full response."""
        raise NotImplementedError

    @abstractmethod
    def stream(self, request: LLMRequest) -> Iterator[str]:
        """Run a streaming completion, yielding text chunks as they arrive."""
        raise NotImplementedError

    @abstractmethod
    def embeddings(
        self, texts: List[str], model: Optional[str] = None
    ) -> List[List[float]]:
        """Return an embedding vector for each input text."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Shared helpers                                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _split_system(request: LLMRequest) -> Tuple[Optional[str], List[Dict[str, str]]]:
        """Separate system text from the user/assistant turn messages.

        Providers like Anthropic and Gemini take the system prompt as a
        dedicated parameter rather than an in-line message. Any ``request.system``
        plus any SYSTEM-role messages are merged into a single system string.
        """
        system_parts: List[str] = []
        if request.system:
            system_parts.append(request.system)

        messages: List[Dict[str, str]] = []
        for message in request.messages:
            if message.role == LLMRole.SYSTEM:
                system_parts.append(message.content)
            else:
                messages.append({"role": message.role.value, "content": message.content})

        system = "\n\n".join(system_parts) if system_parts else None
        return system, messages
