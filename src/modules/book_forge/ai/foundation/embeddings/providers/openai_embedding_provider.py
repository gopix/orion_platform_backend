"""OpenAI implementation of the embedding provider interface.

Communicates with the OpenAI Embeddings API and nothing else:

    EmbeddingRequest -> extract chunk text -> call OpenAI -> receive vectors
    -> build EmbeddingResponse

Batching lives here, hidden from the service: many chunks become as few API calls
as the batch size allows. Statistics are intentionally NOT computed (that's the
service's job); vendor errors are translated into ``EmbeddingException``.
"""
import os
from typing import Iterable, List, Optional

from src.core.config import settings
from src.modules.book_forge.ai.foundation.embeddings.exceptions import EmbeddingException
from src.modules.book_forge.ai.foundation.embeddings.models import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)
from src.modules.book_forge.ai.foundation.embeddings.providers.base_embedding_provider import (
    BaseEmbeddingProvider,
)

PROVIDER_NAME = "openai"
# Max inputs per Embeddings API call. Large enough to be efficient, small enough
# to stay well within request limits; token-limit splitting would also live here.
DEFAULT_BATCH_SIZE = 100


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """Talks to the OpenAI Embeddings API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._api_key = (
            api_key
            or getattr(settings, "openai_api_key", None)
            or os.getenv("OPENAI_API_KEY")
        )
        self._batch_size = max(1, batch_size)
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - depends on env
                raise EmbeddingException(
                    "The 'openai' package is not installed.",
                    details={"provider": PROVIDER_NAME},
                    cause=exc,
                )
            if not self._api_key:
                raise EmbeddingException(
                    "OPENAI_API_KEY is not configured.",
                    details={"provider": PROVIDER_NAME},
                )
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def generate_embeddings(self, request: EmbeddingRequest) -> EmbeddingResponse:
        texts = self._extract_texts(request)
        # No content to embed — return an empty response without an API call.
        if not texts:
            return EmbeddingResponse(
                model=request.model,
                usage=EmbeddingUsage(provider=PROVIDER_NAME, model=request.model),
            )

        client = self._get_client()
        embeddings: List[List[float]] = []
        total_tokens = 0

        try:
            for batch in self._batched(texts, self._batch_size):
                response = client.embeddings.create(model=request.model, input=batch)
                # Sort by index to guarantee alignment with the input order.
                items = sorted(response.data, key=lambda item: item.index)
                embeddings.extend(item.embedding for item in items)
                total_tokens += self._usage_tokens(response)
        except EmbeddingException:
            raise
        except Exception as exc:  # noqa: BLE001 - translated to a domain error
            raise EmbeddingException(
                f"OpenAI embeddings request failed: {exc}",
                details={
                    "provider": PROVIDER_NAME,
                    "status_code": getattr(exc, "status_code", None),
                },
                cause=exc,
            )

        vectors = self._build_vectors(request, embeddings)
        usage = EmbeddingUsage(
            total_tokens=total_tokens,
            provider=PROVIDER_NAME,
            model=request.model,
        )
        # Statistics are left default — the service computes them.
        return EmbeddingResponse(model=request.model, vectors=vectors, usage=usage)

    # ------------------------------------------------------------------ #
    # Internals                                                          #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _batched(items: List[str], size: int) -> Iterable[List[str]]:
        for start in range(0, len(items), size):
            yield items[start : start + size]

    @staticmethod
    def _usage_tokens(response) -> int:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0
        return getattr(usage, "total_tokens", 0) or 0
