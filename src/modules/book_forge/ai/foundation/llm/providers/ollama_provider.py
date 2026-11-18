"""Ollama (local models) implementation of the LLM provider interface.

Talks to a running Ollama server over its HTTP API. No API key is required;
the server URL defaults to http://localhost:11434 and can be overridden with
the OLLAMA_HOST environment variable.
"""
import json
import os
from typing import Iterator, List, Optional

from src.core.config import settings
from src.modules.book_forge.ai.foundation.llm.models import LLMRequest, LLMResponse, LLMUsage
from src.modules.book_forge.ai.foundation.llm.providers.base_provider import BaseLLMProvider

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_TIMEOUT = 120


class OllamaProvider(BaseLLMProvider):
    """Talks to a local Ollama server's /api/chat and /api/embeddings endpoints."""

    def __init__(self, host: Optional[str] = None):
        self._host = (
            host or settings.ollama_host or os.getenv("OLLAMA_HOST") or DEFAULT_HOST
        ).rstrip("/")

    def _requests(self):
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError("The 'requests' package is not installed.") from exc
        return requests

    def _options(self, request: LLMRequest) -> dict:
        options = {"num_predict": request.max_tokens}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.stop_sequences:
            options["stop"] = request.stop_sequences
        return options

    def _messages(self, request: LLMRequest) -> List[dict]:
        system, messages = self._split_system(request)
        if system:
            return [{"role": "system", "content": system}] + messages
        return messages

    def generate(self, request: LLMRequest) -> LLMResponse:
        requests = self._requests()
        payload = {
            "model": request.model,
            "messages": self._messages(request),
            "stream": False,
            "options": self._options(request),
        }
        response = requests.post(
            f"{self._host}/api/chat", json=payload, timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()

        usage = LLMUsage(
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )
        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            model=data.get("model", request.model),
            usage=usage,
            stop_reason=data.get("done_reason"),
            response_id=None,
        )

    def stream(self, request: LLMRequest) -> Iterator[str]:
        requests = self._requests()
        payload = {
            "model": request.model,
            "messages": self._messages(request),
            "stream": True,
            "options": self._options(request),
        }
        with requests.post(
            f"{self._host}/api/chat",
            json=payload,
            stream=True,
            timeout=DEFAULT_TIMEOUT,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                content = chunk.get("message", {}).get("content")
                if content:
                    yield content

    def embeddings(
        self, texts: List[str], model: Optional[str] = None
    ) -> List[List[float]]:
        requests = self._requests()
        embed_model = model or request_default_embed_model()
        vectors: List[List[float]] = []
        for text in texts:
            response = requests.post(
                f"{self._host}/api/embeddings",
                json={"model": embed_model, "prompt": text},
                timeout=DEFAULT_TIMEOUT,
            )
            response.raise_for_status()
            vectors.append(response.json().get("embedding", []))
        return vectors


def request_default_embed_model() -> str:
    """Default embedding model for Ollama; override by passing ``model``."""
    return os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
