"""OpenAI implementation of the LLM provider interface."""
import os
from typing import Iterator, List, Optional

from src.core.config import settings
from src.modules.book_forge.ai.foundation.llm.models import LLMRequest, LLMResponse, LLMUsage
from src.modules.book_forge.ai.foundation.llm.providers.base_provider import BaseLLMProvider

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class OpenAIProvider(BaseLLMProvider):
    """Talks to the OpenAI Chat Completions and Embeddings APIs."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on env
                raise RuntimeError("The 'openai' package is not installed.") from exc
            if not self._api_key:
                raise RuntimeError("OPENAI_API_KEY is not configured.")
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def _to_messages(self, request: LLMRequest) -> List[dict]:
        """OpenAI takes the system prompt as an inline 'system' message."""
        system, messages = self._split_system(request)
        if system:
            return [{"role": "system", "content": system}] + messages
        return messages

    def _build_kwargs(self, request: LLMRequest) -> dict:
        kwargs = {
            "model": request.model,
            "messages": self._to_messages(request),
            "max_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.stop_sequences:
            kwargs["stop"] = request.stop_sequences
        return kwargs

    def generate(self, request: LLMRequest) -> LLMResponse:
        client = self._get_client()
        response = client.chat.completions.create(**self._build_kwargs(request))

        choice = response.choices[0]
        usage = LLMUsage(
            input_tokens=getattr(response.usage, "prompt_tokens", 0),
            output_tokens=getattr(response.usage, "completion_tokens", 0),
        )
        return LLMResponse(
            content=choice.message.content or "",
            model=getattr(response, "model", request.model),
            usage=usage,
            stop_reason=getattr(choice, "finish_reason", None),
            response_id=getattr(response, "id", None),
        )

    def stream(self, request: LLMRequest) -> Iterator[str]:
        client = self._get_client()
        stream = client.chat.completions.create(
            stream=True, **self._build_kwargs(request)
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            if content:
                yield content

    def embeddings(
        self, texts: List[str], model: Optional[str] = None
    ) -> List[List[float]]:
        client = self._get_client()
        response = client.embeddings.create(
            model=model or DEFAULT_EMBEDDING_MODEL, input=texts
        )
        return [item.embedding for item in response.data]
