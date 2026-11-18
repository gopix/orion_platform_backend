"""Vector database exception types.

    VectorStoreException  (base)
      ├── InvalidVectorProviderException   (factory: provider can't be resolved)
      └── VectorSearchException             (search operation failed)
"""
from src.modules.book_forge.ai.foundation.vector_store.exceptions.invalid_vector_provider_exception import (
    InvalidVectorProviderException,
)
from src.modules.book_forge.ai.foundation.vector_store.exceptions.vector_search_exception import (
    VectorSearchException,
)
from src.modules.book_forge.ai.foundation.vector_store.exceptions.vector_store_exception import (
    VectorStoreException,
)

__all__ = [
    "VectorStoreException",
    "InvalidVectorProviderException",
    "VectorSearchException",
]
