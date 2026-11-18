"""LLM orchestration service.

This is the single entry point the rest of the application uses for LLM calls.
Modules depend on ``LLMService`` (or the shared ``llm_service`` singleton) and
never instantiate a provider directly. The service owns provider selection,
lazy instantiation, and caching.

Providers are selected with the ``LLMProvider`` enum (not bare strings)::

    from src.modules.book_forge.ai.foundation.llm.providers import LLMProvider
    llm_service.generate(request, provider=LLMProvider.ANTHROPIC)
"""
import time
from typing import Dict, Iterator, List, Optional, Union

from src.core.config import settings
from src.core.logger import get_logger
from src.modules.book_forge.ai.foundation.llm.factory import LLMProviderFactory
from src.modules.book_forge.ai.foundation.llm.models import LLMRequest, LLMResponse
from src.modules.book_forge.ai.foundation.llm.providers import BaseLLMProvider, LLMProvider
from src.modules.book_forge.ai.foundation.llm.utils.pricing import compute_cost

logger = get_logger(__name__)

# A provider may be given as the enum (preferred) or a string (coerced).
ProviderArg = Union[LLMProvider, str, None]


class LLMService:
    """Orchestrates LLM requests across configurable providers.

    Provider *creation* is delegated to ``LLMProviderFactory``; this class only
    handles orchestration: default selection, instance caching, logging, and
    cost enrichment.
    """

    def __init__(self, default_provider: ProviderArg = None):
        # settings.llm_provider is a string from config/.env; coerce to the enum.
        self._default_provider: LLMProvider = LLMProvider.coerce(
            default_provider or settings.llm_provider
        )
        # Cache of instantiated providers, keyed by the enum.
        self._instances: Dict[LLMProvider, BaseLLMProvider] = {}

    def _resolve_key(self, provider: ProviderArg) -> LLMProvider:
        return (
            self._default_provider
            if provider is None
            else LLMProvider.coerce(provider)
        )

    def get_provider(self, provider: ProviderArg = None) -> BaseLLMProvider:
        """Resolve the provider, building it via the factory on first use."""
        key = self._resolve_key(provider)

        if key not in self._instances:
            logger.info("Instantiating LLM provider '%s'", key.value)
            self._instances[key] = LLMProviderFactory.create(key)

        return self._instances[key]

    def generate(
        self, request: LLMRequest, provider: ProviderArg = None
    ) -> LLMResponse:
        """Run a non-streaming completion via the selected provider (logged)."""
        key = self._resolve_key(provider)
        client = self.get_provider(key)

        start = time.perf_counter()
        response: Optional[LLMResponse] = None
        error: Optional[BaseException] = None
        try:
            response = client.generate(request)
            return response
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            if response is not None:
                self._enrich_usage(response, key, request.model, duration_ms)
            self._log_call(key, request, response, duration_ms, error)

    def stream(
        self, request: LLMRequest, provider: ProviderArg = None
    ) -> Iterator[str]:
        """Run a streaming completion, yielding text chunks (logged on completion)."""
        key = self._resolve_key(provider)
        client = self.get_provider(key)
        return self._logged_stream(key, request, client)

    def _logged_stream(
        self, provider: LLMProvider, request: LLMRequest, client: BaseLLMProvider
    ) -> Iterator[str]:
        start = time.perf_counter()
        error: Optional[BaseException] = None
        try:
            for chunk in client.stream(request):
                yield chunk
        except BaseException as exc:  # noqa: BLE001 - re-raised after logging
            error = exc
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            # Streaming provides no usage/token totals, so cost is not computed.
            self._log_call(provider, request, None, duration_ms, error, streaming=True)

    def embeddings(
        self,
        texts: List[str],
        model: Optional[str] = None,
        provider: ProviderArg = None,
    ) -> List[List[float]]:
        """Return embedding vectors for the given texts via the selected provider."""
        return self.get_provider(provider).embeddings(texts, model=model)

    def _enrich_usage(
        self,
        response: LLMResponse,
        provider: LLMProvider,
        model: str,
        duration_ms: float,
    ) -> None:
        """Populate the cost-tracking fields on ``response.usage`` in place."""
        usage = response.usage
        usage.provider = provider.value
        usage.model = model
        usage.latency_ms = duration_ms
        usage.estimated_cost = compute_cost(model, usage)

    def _log_call(
        self,
        provider: LLMProvider,
        request: LLMRequest,
        response: Optional[LLMResponse],
        duration_ms: float,
        error: Optional[BaseException],
        streaming: bool = False,
    ) -> None:
        """Emit one structured log line per LLM call: provider, model, tokens,
        cost, duration, success."""
        success = error is None
        usage = response.usage if response is not None else None

        if usage is not None:
            cost_str = (
                f"${usage.estimated_cost:.6f}"
                if usage.estimated_cost is not None
                else "n/a"
            )
            tokens_str = (
                f"{usage.input_tokens}in/{usage.output_tokens}out "
                f"(total={usage.total_tokens})"
            )
        else:
            cost_str = "n/a"
            tokens_str = "n/a" if streaming else "0in/0out (total=0)"

        log = logger.info if success else logger.error
        log(
            "LLM call | provider=%s model=%s%s | request_id=%s project_id=%s "
            "document_id=%s user_id=%s | tokens=%s cost=%s | duration_ms=%.1f | "
            "success=%s%s",
            provider.value,
            request.model,
            " (stream)" if streaming else "",
            request.request_id,
            request.project_id,
            request.document_id,
            request.user_id,
            tokens_str,
            cost_str,
            duration_ms,
            success,
            f" | error={type(error).__name__}: {error}" if error else "",
        )


# Shared singleton — import this from other modules.
llm_service = LLMService()
