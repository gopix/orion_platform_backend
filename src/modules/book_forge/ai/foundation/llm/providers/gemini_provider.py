"""Google Gemini implementation of the LLM provider interface."""
import os
from typing import Iterator, List, Optional

from src.core.config import settings
from src.modules.book_forge.ai.foundation.llm.models import LLMRequest, LLMResponse, LLMUsage
from src.modules.book_forge.ai.foundation.llm.providers.base_provider import BaseLLMProvider

DEFAULT_EMBEDDING_MODEL = "models/text-embedding-004"

# Map our roles to Gemini's ('assistant' is called 'model' in Gemini).
_ROLE_MAP = {"user": "user", "assistant": "model"}


class GeminiProvider(BaseLLMProvider):
    """Talks to the Google Generative AI (Gemini) API."""

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = (
            api_key
            or settings.gemini_api_key
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        self._configured = False

    def _ensure_configured(self):
        try:
            import google.generativeai as genai
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(
                "The 'google-generativeai' package is not installed."
            ) from exc
        if not self._api_key:
            raise RuntimeError("GEMINI_API_KEY / GOOGLE_API_KEY is not configured.")
        if not self._configured:
            genai.configure(api_key=self._api_key)
            self._configured = True
        return genai

    def _build_model_and_contents(self, request: LLMRequest):
        genai = self._ensure_configured()
        system, messages = self._split_system(request)

        generation_config = {"max_output_tokens": request.max_tokens}
        if request.temperature is not None:
            generation_config["temperature"] = request.temperature
        if request.stop_sequences:
            generation_config["stop_sequences"] = request.stop_sequences

        model = genai.GenerativeModel(
            model_name=request.model,
            system_instruction=system,
            generation_config=generation_config,
        )
        contents = [
            {"role": _ROLE_MAP.get(m["role"], "user"), "parts": [m["content"]]}
            for m in messages
        ]
        return model, contents

    def generate(self, request: LLMRequest) -> LLMResponse:
        model, contents = self._build_model_and_contents(request)
        response = model.generate_content(contents)

        usage_meta = getattr(response, "usage_metadata", None)
        usage = LLMUsage(
            input_tokens=getattr(usage_meta, "prompt_token_count", 0) if usage_meta else 0,
            output_tokens=getattr(usage_meta, "candidates_token_count", 0) if usage_meta else 0,
        )
        return LLMResponse(
            content=getattr(response, "text", "") or "",
            model=request.model,
            usage=usage,
            stop_reason=None,
            response_id=None,
        )

    def stream(self, request: LLMRequest) -> Iterator[str]:
        model, contents = self._build_model_and_contents(request)
        for chunk in model.generate_content(contents, stream=True):
            text = getattr(chunk, "text", None)
            if text:
                yield text

    def embeddings(
        self, texts: List[str], model: Optional[str] = None
    ) -> List[List[float]]:
        genai = self._ensure_configured()
        result = genai.embed_content(
            model=model or DEFAULT_EMBEDDING_MODEL, content=texts
        )
        # embed_content returns {'embedding': [...]} for one input, or a list for many.
        embedding = result["embedding"]
        if embedding and isinstance(embedding[0], (int, float)):
            return [embedding]
        return embedding
