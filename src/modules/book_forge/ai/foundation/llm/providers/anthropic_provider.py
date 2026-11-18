"""Anthropic (Claude) implementation of the LLM provider interface."""
import os
from typing import Iterator, List, Optional

from src.core.config import settings
from src.modules.book_forge.ai.foundation.llm.models import LLMRequest, LLMResponse, LLMUsage
from src.modules.book_forge.ai.foundation.llm.providers.base_provider import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    """Talks to the Anthropic Messages API."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from anthropic import Anthropic
            except ImportError as exc:  # pragma: no cover - depends on env
                raise RuntimeError(
                    "The 'anthropic' package is not installed."
                ) from exc
            if not self._api_key:
                raise RuntimeError("ANTHROPIC_API_KEY is not configured.")
            self._client = Anthropic(api_key=self._api_key)
        return self._client

    def _build_kwargs(self, request: LLMRequest) -> dict:
        system, messages = self._split_system(request)
        kwargs = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.stop_sequences:
            kwargs["stop_sequences"] = request.stop_sequences
        return kwargs

    def generate(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        response = client.messages.create(**self._build_kwargs(request))

        text = "".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        )
        usage = LLMUsage(
            input_tokens=getattr(response.usage, "input_tokens", 0),
            output_tokens=getattr(response.usage, "output_tokens", 0),
        )
        return LLMResponse(
            content=text,
            model=getattr(response, "model", request.model),
            usage=usage,
            stop_reason=getattr(response, "stop_reason", None),
            response_id=getattr(response, "id", None),
        )

    def stream(self, request: LLMRequest) -> Iterator[str]:
        client = self._get_client()
        with client.messages.stream(**self._build_kwargs(request)) as stream:
            for text in stream.text_stream:
                yield text

    def embeddings(
        self, texts: List[str], model: Optional[str] = None
    ) -> List[List[float]]:
        raise NotImplementedError(
            "Anthropic does not offer an embeddings API; use a dedicated "
            "embeddings provider (e.g. OpenAI, Gemini, or Voyage AI)."
        )
