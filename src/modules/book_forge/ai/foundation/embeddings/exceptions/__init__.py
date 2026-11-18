"""Chunking-parallel exception hierarchy for the embeddings module.

    EmbeddingException  (base)
      ├── InvalidEmbeddingProviderException   (factory: provider can't be resolved)
      └── EmbeddingValidationException         (service: request is invalid)
"""
from src.modules.book_forge.ai.foundation.embeddings.exceptions.embedding_exception import (
    EmbeddingException,
)
from src.modules.book_forge.ai.foundation.embeddings.exceptions.embedding_validation_exception import (
    EmbeddingValidationException,
)
from src.modules.book_forge.ai.foundation.embeddings.exceptions.invalid_embedding_provider_exception import (
    InvalidEmbeddingProviderException,
)

__all__ = [
    "EmbeddingException",
    "InvalidEmbeddingProviderException",
    "EmbeddingValidationException",
]
